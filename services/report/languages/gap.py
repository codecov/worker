from io import BytesIO
from json import dumps, loads

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor


class GapProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return detect(first_line)

    def process(
        self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None
    ):
        if isinstance(content, dict):
            content = dumps(content)
        if isinstance(content, str):
            content = content.encode()
        return from_string(content, path_fixer, ignored_lines, sessionid)


def detect(string: bytes):
    try:
        val = loads(string)
        return "Type" in val and "File" in val
    except (TypeError, ValueError):
        return False


def from_string(string, fix, ignored_lines, sessionid):
    # https://github.com/codecov/support/issues/253
    report = Report()
    _file = None
    skip = True
    for encoded_line in BytesIO(string):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if line:
            line = loads(line)
            if line["Type"] == "S":
                if _file is not None:
                    report.append(_file)
                filename = fix(line["File"])
                if filename:
                    _file = ReportFile(filename, ignore=ignored_lines.get(filename))
                    skip = False
                else:
                    skip = True

            elif skip:
                continue

            else:
                coverage = 0 if line["Type"] == "R" else 1
                _file[line["Line"]] = ReportLine.create(
                    coverage, None, [[sessionid, coverage]]
                )

    # append last file
    report.append(_file)
    return report
