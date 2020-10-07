import re

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class LuaProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line, name):
        return detect(content)

    def process(
        self, name, content: bytes, path_fixer, ignored_lines, sessionid, repo_yaml=None
    ):
        return from_txt(content, path_fixer, ignored_lines, sessionid)


docs = re.compile(r"^=+\n", re.M).split


def detect(report: bytes):
    return report[:7] == b"======="


def from_txt(string: bytes, fix, ignored_lines, sessionid):
    filename = None
    report = Report()
    for string in docs(string.decode(errors="replace").replace("\t", " ")):
        string = string.strip()
        if string == "Summary":
            filename = None
            continue

        elif string.endswith((".lua", ".lisp")):
            filename = fix(string)
            if filename is None:
                continue

        elif filename:
            _file = ReportFile(filename, ignore=ignored_lines.get(filename))
            for ln, source in enumerate(string.splitlines(), start=1):
                try:
                    cov = source.strip().split(" ")[0]
                    cov = 0 if cov[-2:] in ("*0", "0") else int(cov)
                    _file[ln] = ReportLine(cov, None, [[sessionid, cov]])

                except Exception:
                    pass

            report.append(_file)

    return report
