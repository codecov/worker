from io import BytesIO

import sentry_sdk
from shared.helpers.numeric import maxint

from services.report.languages.base import BaseLanguageProcessor
from services.report.languages.helpers import remove_non_ascii
from services.report.report_builder import ReportBuilderSession

START_PARTIAL = "\033[0;41m"
END_PARTIAL = "\033[0m"
NAME_COLOR = "\033\x1b[0;36m"


class XCodeProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
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

    @sentry_sdk.trace
    def process(
        self, content: bytes, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_txt(content, report_builder_session)


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


def from_txt(content: bytes, report_builder_session: ReportBuilderSession) -> None:
    _file = None
    ln_i = 1
    cov_i = 0
    for encoded_line in BytesIO(content):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        line = remove_non_ascii(line).strip(" ")
        if not line or line[0] in ("-", "|", "w"):
            continue

        line = line.replace(NAME_COLOR, "")
        if line.endswith(":") and "|" not in line:
            if _file is not None:
                report_builder_session.append(_file)
            # file names could be "relative/path.abc:" or "/absolute/path.abc:"
            # new file
            _file = report_builder_session.create_coverage_file(
                line.replace(END_PARTIAL, "")[1:-1]
            )
            continue

        if _file is None:
            continue

        parts = line.split("|")
        lnl = len(parts)
        if lnl > 1:
            if lnl > 2 and parts[2].strip() == "}":
                # skip ending bracket lines
                continue

            try:
                ln = int(parts[ln_i].strip())
            except Exception:
                # bad xcode line
                if parts[0] == "1":
                    ln_i, cov_i = 0, 1
                    ln = 1
                else:
                    continue

            if parts[2]:
                partials = get_partials_in_line(parts[2])
                if partials:
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            0,
                            partials=partials,
                        ),
                    )
                    continue

            cov_s = parts[cov_i].replace("E", "").strip()
            if cov_s != "":
                try:
                    if "k" in cov_s or "K" in cov_s:
                        cov = maxint(str(int(float(cov_s.replace("k", "")) * 1000.0)))
                    elif "m" in cov_s or "M" in cov_s:
                        cov = 99999
                    else:
                        cov = maxint(str(int(float(cov_s))))
                except Exception:
                    cov = 1

                try:
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(cov),
                    )
                except Exception:
                    pass

    if _file is not None:
        report_builder_session.append(_file)
