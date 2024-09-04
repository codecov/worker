import sentry_sdk
from shared.reports.resources import Report

from helpers.exceptions import CorruptRawReportError
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class VOneProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return "coverage" in content or "RSpec" in content or "MiniTest" in content

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        if "RSpec" in content:
            content = content["RSpec"]

        elif "MiniTest" in content:
            content = content["MiniTest"]

        return from_json(content, report_builder.create_report_builder_session(name))


def _list_to_dict(lines):
    """
    in:  [None, 1] || {"1": 1}
    out: {"1": 1}
    """
    if isinstance(lines, list):
        if len(lines) > 1:
            return dict(
                [
                    (ln, cov)
                    for ln, cov in enumerate(lines[1:], start=1)
                    if cov is not None
                ]
            )
        else:
            return {}
    elif "lines" in lines:
        # lines format here is
        # { "lines": [ None, None, 1, 1,...] },
        # We add a fake first line because this function starts from line at index 1 not 0
        return _list_to_dict([None] + lines["lines"])
    else:
        return lines or {}


def from_json(json: str, report_builder_session: ReportBuilderSession) -> Report:
    if isinstance(json["coverage"], dict):
        # messages = json.get('messages', {})
        for fn, lns in json["coverage"].items():
            fn = report_builder_session.path_fixer(fn)
            if fn is None:
                continue

            lns = _list_to_dict(lns)
            if lns:
                report_file_obj = report_builder_session.file_class(
                    fn, ignore=report_builder_session.ignored_lines.get(fn)
                )

                for ln, cov in lns.items():
                    try:
                        line_number = int(ln)
                    except ValueError:
                        raise CorruptRawReportError(
                            "v1",
                            "file dictionaries expected to have integers, not strings",
                        )
                    if line_number > 0:
                        if isinstance(cov, str):
                            try:
                                int(cov)
                            except Exception:
                                pass
                            else:
                                cov = int(cov)

                        # message = messages.get(fn, {}).get(ln)
                        coverage_type = (
                            CoverageType.branch
                            if type(cov) in (str, bool)
                            else CoverageType.line
                        )
                        report_file_obj.append(
                            line_number,
                            report_builder_session.create_coverage_line(
                                cov,
                                coverage_type,
                            ),
                        )

                report_builder_session.append(report_file_obj)
        return report_builder_session.output_report()
