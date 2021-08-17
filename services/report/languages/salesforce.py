from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor


class SalesforceProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(type(content) is list) and "name" in content[0]

    def process(
        self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None
    ):
        return from_json(content, path_fixer, ignored_lines, sessionid)


def from_json(json, fix, ignored_lines, sessionid):
    report = Report()
    for obj in json:
        if obj and obj.get("name") and obj.get("lines"):
            fn = fix(obj["name"] + (".cls" if "." not in obj["name"] else ""))
            if fn is None:
                continue

            _file = ReportFile(fn, ignore=ignored_lines.get(fn))
            for ln, cov in obj["lines"].items():
                _file[int(ln)] = ReportLine.create(
                    coverage=cov, sessions=[[sessionid, cov]]
                )

            report.append(_file)

    return report
