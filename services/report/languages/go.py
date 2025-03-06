from collections import defaultdict
from io import BytesIO
from itertools import groupby

import sentry_sdk
from shared.utils import merge
from shared.utils.merge import LineType, line_type, partials_to_line

from helpers.exceptions import CorruptRawReportError
from services.report.languages.base import BaseLanguageProcessor
from services.report.languages.helpers import Region, SourceLocation
from services.report.report_builder import ReportBuilderSession


class GoProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        return content[:6] == b"mode: " or ".go:" in first_line

    @sentry_sdk.trace
    def process(
        self, content: bytes, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_txt(content, report_builder_session)


def from_txt(string: bytes, report_builder_session: ReportBuilderSession) -> None:
    partials_as_hits = report_builder_session.yaml_field(
        ("parsers", "go", "partials_as_hits"),
        False,
    )

    # Process the bytes from uploaded report to intermediary representation
    files = process_bytes_into_files(string)

    for filename, lines in files.items():
        _file = report_builder_session.create_coverage_file(filename)
        if _file is None:
            continue

        for ln, partials in lines.items():
            best_in_partials = max(map(lambda p: p[2], partials))
            partials = combine_partials(partials)
            if partials:
                cov = partials_to_line(partials)
                cov_to_use = cov
            else:
                cov_to_use = best_in_partials
            if partials_as_hits and line_type(cov_to_use) == LineType.partial:
                cov_to_use = 1

            _line = report_builder_session.create_coverage_line(cov_to_use)
            _file.append(ln, _line)

        report_builder_session.append(_file)


def process_bytes_into_files(string: bytes) -> dict[str, dict[int, set]]:
    """
    mode: count
    github.com/codecov/sample_go/sample_go.go:7.14,9.2 1 1
    github.com/codecov/sample_go/sample_go.go:11.26,13.2 1 1
    github.com/codecov/sample_go/sample_go.go:15.19,17.2 1 0

    Ending bracket is here                             v
    github.com/codecov/sample_go/sample_go.go:15.19,17.2 1 0

    All other continuation > .2 should continue
    github.com/codecov/sample_go/sample_go.go:15.19,17.9 1 0

    Need to be cautious of customers who have reports merged in the following way:
    FILE:1.0,2.0 1 0
    ...
    FILE:1.0,2.0 1 1
    ...
    FILE:1.0,2.0 1 0
    Need to respect the coverage

    Line format explanation:
        - https://github.com/golang/go/blob/0104a31b8fbcbe52728a08867b26415d282c35d2/src/cmd/cover/profile.go#L56
        - `name.go:line.column,line.column numberOfStatements count`
    """

    files: dict[str, dict[int, set]] = {}

    for encoded_line in BytesIO(string):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if not line or line.startswith("mode: "):
            continue

        split = line.split(":", 1)
        # File outline e.g., "github.com/nfisher/rsqf/rsqf.go:19: calcP 100.0%"
        if len(split) < 2 or not split[1] or split[1].endswith("%"):
            continue

        filename = split[0]
        try:
            region = parse_coverage(split[1])
        except ValueError:
            # FIXME: do we actually want to raise an error here?
            # Why not just skip over invalid lines, as the coverage file likely
            # contains other valid lines we can use.
            raise CorruptRawReportError(
                "name.go:line.column,line.column numberOfStatements hits",
                "Go coverage line does not match expected format",
            )

        lines = files.setdefault(filename, defaultdict(set))

        # add start of line
        if region.start.line == region.end.line:
            lines[region.start.line].add(
                (region.start.column, region.end.column, region.hits)
            )
        else:
            lines[region.start.line].add((region.start.column, None, region.hits))
            # add middles
            for ln in range(region.start.line + 1, region.end.line):
                lines[ln].add((0, None, region.hits))
            if region.end.column > 2:
                # add end of line
                lines[region.end.line].add((None, region.end.column, region.hits))

    return files


def parse_coverage(line: str) -> Region:
    region_str, _num_statements, hits = line.split(" ", 2)
    start, end = region_str.split(",", 1)
    start_line, start_column = start.split(".", 1)
    end_line, end_column = end.split(".", 1)
    return Region(
        start=SourceLocation(line=int(start_line), column=int(start_column)),
        end=SourceLocation(line=int(end_line), column=int(end_column)),
        hits=int(hits),
    )


def combine_partials(partials):
    """
        [(INCLUSIVE, EXCLUSIVE, HITS), ...]
        | . . . . . |
     in:    0+         (2, None, 0)
     in:  1   1        (1, 3, 1)
    out:  1 1 1 0 0
    out:  1   1 0+     (1, 3, 1), (4, None, 0)
    """
    # only 1 partial: return same
    if len(partials) == 1:
        return list(partials)

    columns = defaultdict(list)
    # fill in the partials WITH end values: (_, X, _)
    for sc, ec, cov in partials:
        if ec is not None:
            for c in range(sc or 0, ec):
                columns[c].append(cov)

    # get the last column number (+1 for exclusiveness)
    lc = (
        max(columns.keys()) if columns else max([sc or 0 for (sc, ec, cov) in partials])
    ) + 1
    # hits for (lc, None, eol)
    eol = []

    # fill in the partials WITHOUT end values: (_, None, _)
    for sc, ec, cov in partials:
        if ec is None:
            for c in range(sc or 0, lc):
                columns[c].append(cov)
            eol.append(cov)

    columns = [(c, merge.merge_all(cov)) for c, cov in columns.items()]

    # sum all the line hits && sort and group lines based on hits
    columns = groupby(sorted(columns), lambda c: c[1])

    results = []
    for cov, cols in columns:
        # unpack iter
        cols = list(cols)
        # sc from first column
        # ec from last (or +1 if singular)
        results.append([cols[0][0], (cols[-1] if cols else cols[0])[0] + 1, cov])

    # remove duds
    if results:
        fp = results[0]
        if fp[0] == 0 and fp[1] == 1:
            results.pop(0)
            if not results:
                return [[0, None, fp[2]]]

        # if there is eol data
        if eol:
            eol = merge.merge_all(eol)
            # if the last partial ec == lc && same hits
            lr = results[-1]
            if lr[1] == lc and lr[2] == eol:
                # then replace the last partial with no end
                results[-1] = [lr[0], None, eol]
            else:
                # else append a new eol partial
                results.append([lc, None, eol])

    return results or None
