import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class ElmProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and bool(content.get("coverageData"))

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def from_json(json: dict, report_builder_session: ReportBuilderSession) -> Report:
    for name, data in json["coverageData"].items():
        _file = report_builder_session.create_coverage_file(json["moduleMap"][name])
        if _file is None:
            continue

        for sec in data:
            cov = sec.get("count", 0)
            complexity = sec.get("complexity")
            sl, sc = sec["from"]["line"], sec["from"]["column"]
            el, ec = sec["to"]["line"], sec["to"]["column"]
            _file.append(
                sl,
                report_builder_session.create_coverage_line(
                    cov,
                    complexity=complexity,
                    partials=[[sc, ec if el == sl else None, cov]],
                ),
            )
            if el > sl:
                for ln in range(sl, el):
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            cov,
                            complexity=complexity,
                        ),
                    )
                _file.append(
                    sl,
                    report_builder_session.create_coverage_line(
                        cov,
                        complexity=complexity,
                        partials=[[None, ec, cov]],
                    ),
                )

        report_builder_session.append(_file)

    return report_builder_session.output_report()
