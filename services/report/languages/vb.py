import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class VbProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content.tag == "results")

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        return from_xml(content, path_fixer, ignored_lines, sessionid)


def from_xml(xml, fix, ignored_lines, sessionid):
    report = Report()
    for module in xml.iter("module"):
        file_by_source = {}
        # loop through sources
        for sf in module.iter("source_file"):
            filename = fix(sf.attrib["path"].replace("\\", "/"))
            if filename:
                file_by_source[sf.attrib["id"]] = ReportFile(
                    filename, ignore=ignored_lines.get(filename)
                )

        if file_by_source:
            # loop through each line
            for line in module.iter("range"):
                line = line.attrib
                _file = file_by_source.get(line["source_id"])
                if _file is not None:
                    coverage = line["covered"]
                    coverage = (
                        1 if coverage == "yes" else 0 if coverage == "no" else True
                    )
                    for ln in range(int(line["start_line"]), int(line["end_line"]) + 1):
                        _file[ln] = ReportLine.create(
                            coverage, None, [[sessionid, coverage]]
                        )

            # add files
            for v in file_by_source.values():
                report.append(v)

    return report
