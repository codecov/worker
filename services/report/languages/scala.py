from covreports.reports.resources import Report, ReportFile
from covreports.reports.types import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class ScalaProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return "fileReports" in content

    def process(
        self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None
    ):
        return from_json(content, path_fixer, ignored_lines, sessionid)


def from_json(data_dict, fix, ignored_lines, sessionid):
    report = Report()
    for f in data_dict["fileReports"]:
        filename = fix(f["filename"])
        if filename is None:
            continue
        _file = ReportFile(filename, ignore=ignored_lines.get(filename))
        fs = _file.__setitem__
        for ln, cov in f["coverage"].items():
            fs(int(ln), ReportLine(cov, None, [[sessionid, cov]]))
        report.append(_file)
    return report
