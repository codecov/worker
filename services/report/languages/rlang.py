from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor


class RlangProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return isinstance(content, dict) and content.get("uploader") == "R"

    def process(
        self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None
    ):
        return from_json(content, path_fixer, ignored_lines, sessionid)


def from_json(data_dict, fix, ignored_lines, sessionid):
    """
    Report example

      uploader: R
      files: []
        name:
        coverage: [null]
    """
    report = Report()

    for data in data_dict["files"]:
        filename = fix(data["name"])
        if filename:
            _file = ReportFile(filename, ignore=ignored_lines.get(filename))
            fs = _file.__setitem__
            [
                fs(ln, ReportLine.create(int(cov), None, [[sessionid, int(cov)]]))
                for ln, cov in enumerate(data["coverage"])
                if cov is not None
            ]
            report.append(_file)

    return report
