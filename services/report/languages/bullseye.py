from xml.etree.ElementTree import Element

import sentry_sdk
from timestring import Date

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession


class BullseyeProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return "BullseyeCoverage" in content.tag

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    if max_age := report_builder_session.yaml_field(
        ("codecov", "max_report_age"), "12h ago"
    ):
        build_id = xml.attrib.get("buildId")
        # build_id format has timestamp at the end "4362c668_2020-10-28_17:55:47"
        timestamp = " ".join(build_id.split("_")[1:])
        if timestamp and Date(timestamp) < max_age:
            raise ReportExpiredException("Bullseye report expired %s" % timestamp)

    for folder in xml.iter("{https://www.bullseye.com/covxml}folder"):
        for file in folder.iter("{https://www.bullseye.com/covxml}src"):
            # Get filepath from parent folder(s)
            filepath = ""
            element = file
            while element.getparent().tag == "{https://www.bullseye.com/covxml}folder":
                element = element.getparent()
                filepath = f'{element.attrib.get("name")}/{filepath}'
            filepath += file.attrib.get("name")

            _file = report_builder_session.create_coverage_file(filepath)
            if _file is None:
                continue

            for function in file.iter("{https://www.bullseye.com/covxml}fn"):
                for probe in function.iter("{https://www.bullseye.com/covxml}probe"):
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
                            coverage,
                            _type,
                        ),
                    )
            report_builder_session.append(_file)
