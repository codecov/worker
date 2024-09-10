import sentry_sdk

from helpers.exceptions import CorruptRawReportError
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession


class VOneProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return "coverage" in content or "RSpec" in content or "MiniTest" in content

    @sentry_sdk.trace
    def process(
        self, content: dict, report_builder_session: ReportBuilderSession
    ) -> None:
        if "RSpec" in content:
            content = content["RSpec"]

        elif "MiniTest" in content:
            content = content["MiniTest"]

        return from_json(content, report_builder_session)


def _list_to_dict(lines):
    """
    in:  [None, 1] || {"1": 1}
    out: {"1": 1}
    """
    if isinstance(lines, list):
        if len(lines) > 1:
            return {
                ln: cov for ln, cov in enumerate(lines[1:], start=1) if cov is not None
            }
        else:
            return {}
    elif "lines" in lines:
        # lines format here is
        # { "lines": [ None, None, 1, 1,...] },
        # We add a fake first line because this function starts from line at index 1 not 0
        return _list_to_dict([None] + lines["lines"])
    else:
        return lines or {}


def from_json(json: str, report_builder_session: ReportBuilderSession) -> None:
    if not isinstance(json["coverage"], dict):
        return

    for fn, lns in json["coverage"].items():
        _file = report_builder_session.create_coverage_file(fn)
        if _file is None:
            continue

        lns = _list_to_dict(lns)
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

                coverage_type = (
                    CoverageType.branch
                    if type(cov) in (str, bool)
                    else CoverageType.line
                )
                _file.append(
                    line_number,
                    report_builder_session.create_coverage_line(
                        cov,
                        coverage_type,
                    ),
                )

        report_builder_session.append(_file)
