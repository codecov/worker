import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from io import BytesIO

import sentry_sdk
from shared.reports.resources import ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession

log = logging.getLogger(__name__)


class LcovProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        return b"\nend_of_record" in content

    @sentry_sdk.trace
    def process(
        self, content: bytes, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_txt(content, report_builder_session)


def from_txt(reports: bytes, report_builder_session: ReportBuilderSession) -> None:
    # http://ltp.sourceforge.net/coverage/lcov/geninfo.1.php
    # merge same files
    for string in reports.split(b"\nend_of_record"):
        if (_file := _process_file(string, report_builder_session)) is not None:
            report_builder_session.append(_file)


def _process_file(
    doc: bytes, report_builder_session: ReportBuilderSession
) -> ReportFile | None:
    branches: dict[str, dict[str, int]] = defaultdict(dict)
    fn_lines: set[str] = set()  # lines of function definitions

    JS = False
    CPP = False
    skip_lines: list[str] = []
    _file: ReportFile | None = None

    for encoded_line in BytesIO(doc):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if line == "" or ":" not in line:
            continue

        method, content = line.split(":", 1)
        content = content.strip()
        if method in ("TN", "LF", "LH", "FNF", "FNH", "BRF", "BRH", "FNDA"):
            # TN: test title
            # LF: lines found
            # LH: lines hit
            # FNF: functions found
            # FNH: functions hit
            # BRF: branches found
            # BRH: branches hit
            # FNDA: function data
            continue

        if method == "SF":
            """
            For each source file referenced in the .da file, there is a section
            containing filename and coverage data:

            SF:<absolute path to the source file>
            """
            # file name
            _file = report_builder_session.create_coverage_file(content)
            JS = content[-3:] == ".js"
            CPP = content[-4:] == ".cpp"
            continue

        if _file is None:
            return None

        if method == "DA":
            """
            Then there is a list of execution counts for each instrumented line
            (i.e. a line which resulted in executable code):

            DA:<line number>,<execution count>[,<checksum>]
            """
            #  DA:<line number>,<execution count>[,<checksum>]
            if line.startswith("undefined,"):
                continue

            split = content.split(",", 2)
            if len(split) < 2:
                continue
            line_str = split[0]
            hit = split[1]

            if line_str in ("", "undefined") or hit in ("", "undefined"):
                continue
            if line_str[0] in ("0", "n") or hit[0] in ("=", "s"):
                continue

            try:
                ln = int(line_str)
                cov = parse_int(hit)
            except (ValueError, InvalidOperation):
                continue

            cov = max(cov, 0)  # clamp to 0

            _line = report_builder_session.create_coverage_line(cov)
            _file.append(ln, _line)

        elif method == "FN" and not JS:
            """
            Following is a list of line numbers for each function name found in the
            source file:

            FN:<line number of function start>,<function name>
            """

            split = content.split(",", 1)
            if len(split) < 2:
                continue
            line_str, name = split

            if CPP and name[:2] in ("_Z", "_G"):
                skip_lines.append(line_str)
                continue

            fn_lines.add(line_str)

        elif method == "BRDA" and not JS:
            """
            Branch coverage information is stored with one line per branch:

              BRDA:<line number>,<block number>,<branch number>,<taken>

            Block number and branch number are gcc internal IDs for the branch.
            Taken is either "-" if the basic block containing the branch was never
            executed or a number indicating how often that branch was taken.
            """
            # BRDA:<line number>,<block number>,<branch number>,<taken>
            split = content.split(",", 3)
            if len(split) < 4:
                continue
            line_str, block, branch, taken = split

            if line_str == "1" and _file.name.endswith(".ts"):
                continue

            elif line_str not in ("0", ""):
                branches[line_str]["%s:%s" % (block, branch)] = (
                    0 if taken in ("-", "0") else 1
                )

    if _file is None:
        return None

    # remove skipped branches
    for sl in skip_lines:
        branches.pop(sl, None)

    # work branches
    for line_str, br in branches.items():
        try:
            ln = int(line_str)
        except ValueError:
            continue

        branch_num = len(br.values())
        branch_sum = sum(br.values())
        missing_branches = [bid for bid, cov in br.items() if cov == 0]

        coverage = f"{branch_sum}/{branch_num}"
        coverage_type = (
            CoverageType.method if line_str in fn_lines else CoverageType.branch
        )

        _line = report_builder_session.create_coverage_line(
            coverage,
            coverage_type,
            missing_branches=(missing_branches if missing_branches != [] else None),
        )
        # instead of using `.append`/merge, this rather overwrites the line:
        _file[ln] = _line

    return _file


def parse_int(n: str) -> int:
    if n.isnumeric():
        return int(n)

    # Huge ints may be expressed in scientific notation.
    # int(float(hit)) may lose precision, but Decimal shouldn't.
    return int(Decimal(n))
