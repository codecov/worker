import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import LineSession, ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession


class ElmProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return isinstance(content, dict) and bool(content.get("coverageData"))

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_json(content, report_builder_session)


def from_json(json, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, sessionid = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.sessionid,
    )
    for name, data in json["coverageData"].items():
        fn = path_fixer(json["moduleMap"][name])
        if fn is None:
            continue

        _file = ReportFile(fn, ignore=ignored_lines.get(fn))

        for sec in data:
            cov = sec.get("count", 0)
            complexity = sec.get("complexity")
            sl, sc = sec["from"]["line"], sec["from"]["column"]
            el, ec = sec["to"]["line"], sec["to"]["column"]
            _file[sl] = ReportLine.create(
                coverage=cov,
                sessions=[
                    LineSession(
                        id=sessionid,
                        coverage=cov,
                        partials=[[sc, ec if el == sl else None, cov]],
                    )
                ],
                complexity=complexity,
            )
            if el > sl:
                for ln in range(sl, el):
                    _file[ln] = ReportLine.create(
                        coverage=cov, sessions=[[sessionid, cov]], complexity=complexity
                    )
                _file[sl] = ReportLine.create(
                    coverage=cov,
                    sessions=[
                        LineSession(
                            id=sessionid, coverage=cov, partials=[[None, ec, cov]]
                        )
                    ],
                    complexity=complexity,
                )

        report_builder_session.append(_file)

    return report_builder_session.output_report()
