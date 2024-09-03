import sentry_sdk
from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.path_fixer import PathFixer
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class RlangProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and content.get("uploader") == "R"

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        return from_json(
            content,
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
        )


def from_json(data_dict: dict, fix: PathFixer, ignored_lines: dict, sessionid: int):
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
