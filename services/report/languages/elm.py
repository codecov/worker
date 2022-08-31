import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import LineSession, ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class ElmProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return isinstance(content, dict) and bool(content.get("coverageData"))

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        return from_json(content, path_fixer, ignored_lines, sessionid)


def from_json(json, fix, ignored_lines, sessionid):
    report = Report()
    for name, data in json["coverageData"].items():
        fn = fix(json["moduleMap"][name])
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

        report.append(_file)

    return report
