from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report, ReportFile
from timestring import Date

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)
from services.yaml import read_yaml_field


class CloverProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "coverage" and bool(content.attrib.get("generated"))

    @sentry_sdk.trace
    def process(
        self, name: str, content: Element, report_builder: ReportBuilder
    ) -> Report:
        return from_xml(content, report_builder.create_report_builder_session(name))


def get_end_of_file(filename, xmlfile):
    """
    php reports have shown to include
    exrta coverage data that extend
    past the source code line count
    """
    if filename.endswith(".php"):
        for metrics in xmlfile.iter("metrics"):
            try:
                return int(metrics.attrib["loc"])
            except Exception:
                pass


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, yaml = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.current_yaml,
    )

    if max_age := read_yaml_field(yaml, ("codecov", "max_report_age"), "12h ago"):
        try:
            timestamp = next(xml.iter("coverage")).get("generated")
            if "-" in timestamp:
                t = timestamp.split("-")
                timestamp = t[1] + "-" + t[0] + "-" + t[2]
            if timestamp and Date(timestamp) < max_age:
                # report expired over 12 hours ago
                raise ReportExpiredException("Clover report expired %s" % timestamp)
        except StopIteration:
            pass

    files: dict[str, ReportFile] = {}
    for f in xml.iter("file"):
        filename = f.attrib.get("path") or f.attrib["name"]

        # skip empty file documents
        if (
            "{" in filename
            or ("/vendor/" in ("/" + filename) and filename.endswith(".php"))
            or f.find("line") is None
        ):
            continue

        if filename not in files:
            files[filename] = report_builder_session.file_class(filename)
        _file = files[filename]

        # fix extra lines
        eof = get_end_of_file(filename, f)

        # process coverage
        for line in f.iter("line"):
            attribs = line.attrib
            ln = int(attribs["num"])
            complexity = None

            # skip line
            if ln < 1 or (eof and ln > eof):
                continue

            # [typescript] https://github.com/gotwarlost/istanbul/blob/89e338fcb1c8a7dea3b9e8f851aa55de2bc3abee/lib/report/clover.js#L108-L110
            if attribs["type"] == "cond":
                _type = CoverageType.branch
                t, f = int(attribs["truecount"]), int(attribs["falsecount"])
                if t == f == 0:
                    coverage = "0/2"
                elif t == 0 or f == 0:
                    coverage = "1/2"
                else:
                    coverage = "2/2"

            elif attribs["type"] == "method":
                coverage = int(attribs.get("count") or 0)
                _type = CoverageType.method
                complexity = int(attribs.get("complexity") or 0)
                # <line num="44" type="method" name="doRun" visibility="public" complexity="5" crap="5.20" count="1"/>

            else:
                coverage = int(attribs.get("count") or 0)
                _type = CoverageType.line

            # add line to report
            _file.append(
                ln,
                report_builder_session.create_coverage_line(
                    coverage=coverage,
                    coverage_type=_type,
                    filename=filename,
                    complexity=complexity,
                ),
            )

    for f in files.values():
        report_builder_session.append(f)
    report_builder_session.resolve_paths([(f, path_fixer(f)) for f in files.keys()])
    report_builder_session.ignore_lines(ignored_lines)

    return report_builder_session.output_report()
