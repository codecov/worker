import typing
from io import BytesIO

from shared.helpers.numeric import maxint
from shared.reports.resources import Report
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.languages.helpers import remove_non_ascii
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)

START_PARTIAL = "\033[0;41m"
END_PARTIAL = "\033[0m"
NAME_COLOR = "\033\x1b[0;36m"


class XCodeProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return name.endswith(
            ("app.coverage.txt", "framework.coverage.txt", "xctest.coverage.txt")
        ) or first_line.endswith(
            (
                ".h:",
                ".m:",
                ".swift:",
                ".hpp:",
                ".cpp:",
                ".cxx:",
                ".c:",
                ".C:",
                ".cc:",
                ".cxx:",
                ".c++:",
            )
        )

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        return from_txt(content, report_builder.create_report_builder_session(name))


def get_partials_in_line(line):
    if START_PARTIAL in line:
        partials = []
        while START_PARTIAL in line and END_PARTIAL in line:
            # get start of column
            sc = line.find(START_PARTIAL)

            # remove the START_PARTIAL
            line = line.replace(START_PARTIAL, "", 1).lstrip("\x1b")

            # trim empty. e.g., [0;41m    print("See you later!")[0m
            #                         ^^^^
            ll = len(line)
            line = line.lstrip()
            offset = ll - len(line)

            # get end of column`
            ec = line.find(END_PARTIAL)

            # remove the END_PARTIAL
            line = line.replace(END_PARTIAL, "", 1)

            # add partial
            partials.append([sc + offset, ec + offset, 0])

        return partials


def from_txt(content, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, sessionid = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.sessionid,
    )
    files = {}
    skip = False
    _file = None
    ln_i = 1
    cov_i = 0
    for encoded_line in BytesIO(content):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if line:
            line = remove_non_ascii(line).strip(" ")
            if line[0] not in ("-", "|", "w"):
                line = line.replace(NAME_COLOR, "")
                if line.endswith(":") and "|" not in line:
                    # file names could be "relative/path.abc:" or "/absolute/path.abc:"
                    # new file
                    filename = path_fixer(line.replace(END_PARTIAL, "")[1:-1])
                    # skip empty files
                    skip = filename is None
                    # add new file
                    if not skip:
                        _file = files.setdefault(
                            filename,
                            report_builder_session.file_class(
                                filename,
                                ignore=ignored_lines.get(filename),
                            ),
                        )

                elif skip:
                    continue

                elif _file is not None:
                    line = line.split("|")
                    lnl = len(line)
                    if lnl > 1:
                        if lnl > 2 and line[2].strip() == "}":
                            # skip ending bracket lines
                            continue

                        try:
                            ln = int(line[ln_i].strip())
                        except Exception:
                            # bad xcode line
                            if line[0] == "1":
                                ln_i, cov_i = 0, 1
                                ln = 1
                            else:
                                continue

                        if line[2]:
                            partials = get_partials_in_line(line[2])
                            if partials:
                                _file.append(
                                    ln,
                                    report_builder_session.create_coverage_line(
                                        coverage=0,
                                        coverage_type=CoverageType.line,
                                        partials=partials,
                                    ),
                                )
                                continue

                        cov = line[cov_i].replace("E", "").strip()
                        if cov != "":
                            try:
                                if "k" in cov or "K" in cov:
                                    cov = maxint(
                                        str(int(float(cov.replace("k", "")) * 1000.0))
                                    )
                                elif "m" in cov or "M" in cov:
                                    cov = 99999
                                else:
                                    cov = maxint(str(int(float(cov))))
                            except Exception:
                                cov = 1

                            try:
                                _file.append(
                                    ln, ReportLine.create(cov, None, [[sessionid, cov]])
                                )
                            except Exception:
                                pass

    for val in files.values():
        report_builder_session.append(val)
    return report_builder_session.output_report()
