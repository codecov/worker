import typing
from collections import defaultdict
from io import BytesIO
from itertools import groupby

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from shared.utils import merge
from shared.utils.merge import LineType, line_type, partials_to_line

from helpers.exceptions import CorruptRawReportError
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder
from services.yaml import read_yaml_field


class GoProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return content[:6] == b"mode: " or ".go:" in first_line

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        return from_txt(
            content,
            path_fixer,
            ignored_lines,
            sessionid,
            read_yaml_field(repo_yaml, ("parsers", "go")) or {},
        )


def from_txt(string: bytes, fix, ignored_lines, sessionid, go_parser_settings):
    """
    mode: count
    github.com/codecov/sample_go/sample_go.go:7.14,9.2 1 1
    github.com/codecov/sample_go/sample_go.go:11.26,13.2 1 1
    github.com/codecov/sample_go/sample_go.go:15.19,17.2 1 0

    Ending bracket is here                             v
    github.com/codecov/sample_go/sample_go.go:15.19,17.2 1 0

    All other continuation > .2 should continue
    github.com/codecov/sample_go/sample_go.go:15.19,17.9 1 0

    Need to be concious of customers whom have reports merged in the following way:
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
    _cur_file = None
    lines = None
    ignored_files = []
    file_name_replacement = {}  # {old_name: new_name}
    files = {}  # {new_name: <lines defaultdict(list)>}
    for encoded_line in BytesIO(string):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if not line:
            continue

        elif line[:6] == "mode: ":
            continue

        # prepare data
        filename, data = line.split(":", 1)
        if data.endswith("%"):
            # File outline e.g., "github.com/nfisher/rsqf/rsqf.go:19: calcP 100.0%"
            continue

        # if we are on the same file name we can pass this
        if filename in ignored_files:
            continue

        if _cur_file != filename:
            _cur_file = filename
            if filename in file_name_replacement:
                filename = file_name_replacement[filename]
            else:
                fixed = fix(filename)

                file_name_replacement[filename] = fixed
                filename = fixed
                if filename is None:
                    ignored_files.append(_cur_file)
                    _cur_file = None
                    continue

            lines = files.setdefault(filename, defaultdict(set))

        columns, _, hits = data.split(" ", 2)
        hits = int(hits)
        sl, el = columns.split(",", 1)
        sl, sc = list(map(int, sl.split(".", 1)))
        try:
            el, ec = list(map(int, el.split(".", 1)))
        except ValueError:
            raise CorruptRawReportError(
                "name.go:line.column,line.column numberOfStatements count",
                "Missing numberOfStatements count\n at the end of the line, or they are not given in the right format",
            )

        # add start of line
        if sl == el:
            lines[sl].add((sc, ec, hits))
        else:
            lines[sl].add((sc, None, hits))
            # add middles
            [lines[ln].add((0, None, hits)) for ln in range(sl + 1, el)]
            if ec > 2:
                # add end of line
                lines[el].add((None, ec, hits))

    # create a file
    report = Report()
    for filename, lines in files.items():
        _file = ReportFile(filename, ignore=ignored_lines.get(filename))
        for ln, partials in lines.items():
            best_in_partials = max(map(lambda p: p[2], partials))
            partials = combine_partials(partials)
            if partials:
                cov = partials_to_line(partials)
                cov_to_use = cov
            else:
                cov_to_use = best_in_partials
            if (
                go_parser_settings.get("partials_as_hits", False)
                and line_type(cov_to_use) == LineType.partial
            ):
                cov_to_use = 1
            _file[ln] = ReportLine.create(cov_to_use, None, [[sessionid, cov_to_use]])
        report.append(_file)

    return report


def combine_partials(partials):
    """
        [(INCLUSIVE, EXCLUSICE, HITS), ...]
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
    [
        [columns[c].append(cov) for c in range(sc or 0, ec)]
        for (sc, ec, cov) in partials
        if ec is not None
    ]

    # get the last column number (+1 for exclusiveness)
    lc = (
        max(columns.keys()) if columns else max([sc or 0 for (sc, ec, cov) in partials])
    ) + 1
    # hits for (lc, None, eol)
    eol = []

    # fill in the partials WITHOUT end values: (_, None, _)
    [
        ([columns[c].append(cov) for c in range(sc or 0, lc)], eol.append(cov))
        for (sc, ec, cov) in partials
        if ec is None
    ]

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
