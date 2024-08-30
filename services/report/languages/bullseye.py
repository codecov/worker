from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report
from timestring import Date

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)
from services.yaml import read_yaml_field


class BullseyeProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return "BullseyeCoverage" in content.tag

    @sentry_sdk.trace
    def process(
        self, name: str, content: Element, report_builder: ReportBuilder
    ) -> Report:
        return from_xml(content, report_builder.create_report_builder_session(name))


def from_xml(xml: Element, report_builder_session: ReportBuilderSession):
    path_fixer, ignored_lines, yaml = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.current_yaml,
    )
    if read_yaml_field(yaml, ("codecov", "max_report_age"), "12h ago"):
        build_id = xml.attrib.get("buildId")
        # build_id format has timestamp at the end "4362c668_2020-10-28_17:55:47"
        timestamp = " ".join(build_id.split("_")[1:])
        if timestamp and Date(timestamp) < read_yaml_field(
            yaml, ("codecov", "max_report_age"), "12h ago"
        ):
            raise ReportExpiredException("Bullseye report expired %s" % timestamp)

    for folder in xml.iter("{https://www.bullseye.com/covxml}folder"):
        for file in folder.iter("{https://www.bullseye.com/covxml}src"):
            # Get filepath from parent folder(s)
            filepath = ""
            element = file
            while element.getparent().tag == "{https://www.bullseye.com/covxml}folder":
                element = element.getparent()
                filepath = f'{element.attrib.get("name")}/{filepath}'
            filename = path_fixer(filepath + file.attrib.get("name"))
            if filename:
                _file = report_builder_session.file_class(filename)
                for function in file.iter("{https://www.bullseye.com/covxml}fn"):
                    for probe in function.iter(
                        "{https://www.bullseye.com/covxml}probe"
                    ):
                        attribs = probe.attrib
                        ln = int(attribs["line"])
                        if attribs["kind"] in ("condition", "decision", "switch-label"):
                            _type = CoverageType.branch

                        elif attribs["kind"] == "function":
                            _type = CoverageType.method
                        else:
                            _type = CoverageType.line

                        if attribs["event"] == "full":
                            coverage = 1
                        elif attribs["event"] == "none":
                            coverage = 0
                        else:
                            coverage = "1/2"
                        _file.append(
                            ln,
                            report_builder_session.create_coverage_line(
                                filename=filename,
                                coverage=coverage,
                                coverage_type=_type,
                            ),
                        )
                report_builder_session.append(_file)
    report_builder_session.ignore_lines(ignored_lines)
    return report_builder_session.output_report()
