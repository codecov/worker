import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class ElmProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and bool(content.get("coverageData"))

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_json(content, report_builder_session)


def from_json(json: dict, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )
    for name, data in json["coverageData"].items():
        fn = path_fixer(json["moduleMap"][name])
        if fn is None:
            continue

        _file = report_builder_session.file_class(name=fn, ignore=ignored_lines.get(fn))

        for sec in data:
            cov = sec.get("count", 0)
            complexity = sec.get("complexity")
            sl, sc = sec["from"]["line"], sec["from"]["column"]
            el, ec = sec["to"]["line"], sec["to"]["column"]
            _file[sl] = report_builder_session.create_coverage_line(
                filename=fn,
                coverage=cov,
                coverage_type=CoverageType.line,
                complexity=complexity,
                partials=[[sc, ec if el == sl else None, cov]],
            )
            if el > sl:
                for ln in range(sl, el):
                    _file[ln] = report_builder_session.create_coverage_line(
                        filename=fn,
                        coverage=cov,
                        coverage_type=CoverageType.line,
                        complexity=complexity,
                    )
                _file[sl] = report_builder_session.create_coverage_line(
                    filename=fn,
                    coverage=cov,
                    coverage_type=CoverageType.line,
                    complexity=complexity,
                    partials=[[None, ec, cov]],
                )

        report_builder_session.append(_file)

    return report_builder_session.output_report()
