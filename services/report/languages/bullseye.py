import typing
from xml.etree.ElementTree import Element

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from timestring import Date

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder
from services.yaml import read_yaml_field


class BullseyeProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return "BullseyeCoverage" in content.tag

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        return from_xml(content, path_fixer, ignored_lines, sessionid, repo_yaml)


def from_xml(xml, fix, ignored_lines, sessionid, yaml):

    if read_yaml_field(yaml, ("codecov", "max_report_age"), "12h ago"):
        build_id = xml.attrib.get("buildId")
        # build_id format has timestamp at the end "4362c668_2020-10-28_17:55:47"
        timestamp = " ".join(build_id.split("_")[1:])
        if timestamp and Date(timestamp) < read_yaml_field(
            yaml, ("codecov", "max_report_age"), "12h ago"
        ):
            raise ReportExpiredException("Bullseye report expired %s" % timestamp)

    report = Report()
    for folder in xml.iter("{https://www.bullseye.com/covxml}folder"):
        for file in folder.iter("{https://www.bullseye.com/covxml}src"):
            # Get filepath from parent folder(s)
            filepath = ""
            element = file
            while element.getparent().tag == "{https://www.bullseye.com/covxml}folder":
                element = element.getparent()
                filepath = f'{element.attrib.get("name")}/{filepath}'
            filename = fix(filepath + file.attrib.get("name"))
            if filename:
                _file = ReportFile(filename)
                for function in file.iter("{https://www.bullseye.com/covxml}fn"):
                    for probe in function.iter(
                        "{https://www.bullseye.com/covxml}probe"
                    ):
                        attribs = probe.attrib
                        ln = int(attribs["line"])
                        if attribs["kind"] in ("condition", "decision", "switch-label"):
                            _type = "b"

                        elif attribs["kind"] == "function":
                            _type = "m"
                        else:
                            _type = None

                        if attribs["event"] == "full":
                            coverage = 1
                        elif attribs["event"] == "none":
                            coverage = 0
                        else:
                            coverage = "1/2"
                        _file.append(
                            ln,
                            ReportLine.create(
                                coverage=coverage,
                                type=_type,
                                sessions=[[sessionid, coverage]],
                            ),
                        )
                report.append(_file)
    report.ignore_lines(ignored_lines)
    return report
