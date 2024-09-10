import logging
from collections import defaultdict
from decimal import Decimal
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
        if _file := _process_file(string, report_builder_session):
            report_builder_session.append(_file)


def _process_file(
    doc: bytes, report_builder_session: ReportBuilderSession
) -> ReportFile:
    _already_informed_of_negative_execution_count = False
    lines = {}
    branches = defaultdict(dict)
    fln, fh = {}, {}
    JS = False
    CPP = False
    skip_lines = []
    _file = None

    for encoded_line in BytesIO(doc):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if line == "" or ":" not in line:
            continue

        method, content = line.split(":", 1)
        content = content.strip()
        if method in ("TN", "LF", "LH", "BRF", "BRH"):
            # TN: test title
            # LF: lines found
            # LH: lines hit
            # FNF: functions found
            # FNH: functions hit
            # BRF: branches found
            # BRH: branches hit
            continue

        elif method == "SF":
            """
            For each source file referenced in the .da file, there is a section
            containing filename and coverage data:

            SF:<absolute path to the source file>
            """
            # file name
            _file = report_builder_session.create_coverage_file(content)
            if _file is None:
                return None

            JS = content[-3:] == ".js"
            CPP = content[-4:] == ".cpp"

        elif method == "DA":
            """
            Then there is a list of execution counts for each instrumented line
            (i.e. a line which resulted in executable code):

            DA:<line number>,<execution count>[,<checksum>]
            """
            #  DA:<line number>,<execution count>[,<checksum>]
            if line.startswith("undefined,"):
                continue

            splited_content = content.split(",")
            line = splited_content[0]
            hit = splited_content[1]
            if line[0] in ("0", "n") or hit[0] in ("=", "s"):
                continue

            if hit == "undefined" or line == "undefined":
                continue

            if hit.isnumeric():
                cov = int(hit)
            else:
                # Huge ints may be expressed in scientific notation.
                # int(float(hit)) may lose precision, but Decimal shouldn't.
                cov = int(Decimal(hit))

            if cov < -1:
                # https://github.com/linux-test-project/lcov/commit/dfec606f3b30e1ac0f4114cfb98b29f91e9edb21
                if not _already_informed_of_negative_execution_count:
                    log.warning(
                        "At least one occurrence of negative execution counts on Lcov",
                        extra=dict(
                            execution_count=cov, lcov_report_filename=_file.name
                        ),
                    )
                    _already_informed_of_negative_execution_count = True
                cov = 0
            coverage_line = report_builder_session.create_coverage_line(cov)
            _file.append(int(line), coverage_line)

        elif method == "FN" and not JS:
            """
            Following is a list of line numbers for each function name found in the
            source file:

            FN:<line number of function start>,<function name>
            """
            line, name = content.split(",", 1)
            if CPP and name[:2] in ("_Z", "_G"):
                skip_lines.append(line)
                continue

            fln[name] = line

        elif method == "FNDA" and not JS:
            #  FNDA:<execution count>,<function name>
            hit, name = content.split(",", 1)
            if CPP and name[0] == "_":
                skip_lines.append(line)
                continue

            if hit:
                if hit.isnumeric():
                    fh[name] = int(hit)
                else:
                    fh[name] = int(Decimal(hit))

        elif method == "BRDA" and not JS:
            """
            Branch coverage information is stored which one line per branch:

              BRDA:<line number>,<block number>,<branch number>,<taken>

            Block  number  and  branch  number are gcc internal IDs for the branch.
            Taken is either "-" if the basic block containing the branch was  never
            executed or a number indicating how often that branch was taken.
            """
            # BRDA:<line number>,<block number>,<branch number>,<taken>
            ln, block, branch, taken = content.split(",", 3)
            if ln == "1" and _file.name.endswith(".ts"):
                continue

            elif ln not in ("0", ""):
                branches[ln]["%s:%s" % (block, branch)] = (
                    0 if taken in ("-", "0") else 1
                )

    # remove skipped
    for sl in skip_lines:
        branches.pop(sl, None)
        lines.pop(sl, None)

    methods = fln.values()

    # work branches
    for ln, br in branches.items():
        s, li = sum(br.values()), len(br.values())
        mb = [bid for bid, cov in br.items() if cov == 0]
        cov = "%s/%s" % (s, li)

        coverage_type = CoverageType.method if ln in methods else CoverageType.branch
        _file.append(
            int(ln),
            report_builder_session.create_coverage_line(
                cov,
                coverage_type,
                missing_branches=(mb if mb != [] else None),
            ),
        )

    return _file
