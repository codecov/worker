import logging
import re
from typing import List
from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report
from timestring import Date, TimestringInvalid

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


class CoberturaProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return bool(
            next(content.iter("coverage"), None)
            or next(content.iter("scoverage"), None)
        )

    @sentry_sdk.trace
    def process(
        self, name: str, content: Element, report_builder: ReportBuilder
    ) -> Report:
        return from_xml(content, report_builder.create_report_builder_session(name))


def Int(value):
    try:
        return int(value)
    except ValueError:
        return int(float(value))


def get_sources_to_attempt(xml) -> List[str]:
    sources = [source.text for source in xml.iter("source")]
    return [s for s in sources if isinstance(s, str) and s.startswith("/")]


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, yaml = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.current_yaml,
    )

    # # process timestamp
    if max_age := read_yaml_field(yaml, ("codecov", "max_report_age"), "12h ago"):
        try:
            timestamp = next(xml.iter("coverage")).get("timestamp")
        except StopIteration:
            try:
                timestamp = next(xml.iter("scoverage")).get("timestamp")
            except StopIteration:
                timestamp = None

        try:
            parsed_datetime = Date(timestamp)
            is_valid_timestamp = True
        except TimestringInvalid:
            parsed_datetime = None
            is_valid_timestamp = False

        if (
            timestamp
            and is_valid_timestamp
            and parsed_datetime
            < max_age
        ):
            # report expired over 12 hours ago
            raise ReportExpiredException("Cobertura report expired " + timestamp)

    handle_missing_conditions = read_yaml_field(
                        yaml,
                        ("parsers", "cobertura", "handle_missing_conditions"),
                        False,
                    )
    partials_as_hits = read_yaml_field(
                        yaml,
                        ("parsers", "cobertura", "partials_as_hits"),
                        False,
                    )

    for _class in xml.iter("class"):
        filename = _class.attrib["filename"]
        _file = report_builder_session.file_class(name=filename)

        for line in _class.iter("line"):
            _line = line.attrib
            ln = _line["number"]
            if ln == "undefined":
                continue
            ln = int(ln)
            if ln > 0:
                coverage = None
                _type = CoverageType.line
                missing_branches = None

                # coverage
                branch = _line.get("branch", "")
                condition_coverage = _line.get("condition-coverage", "")
                if (
                    branch.lower() == "true"
                    and re.search(r"\(\d+\/\d+\)", condition_coverage) is not None
                ):
                    coverage = condition_coverage.split(" ", 1)[1][1:-1]  # 1/2
                    _type = CoverageType.branch
                else:
                    coverage = Int(_line.get("hits"))

                # [python] [scoverage] [groovy] Conditions
                conditions = _line.get("missing-branches", None)
                if conditions:
                    conditions = conditions.split(",")
                    if len(conditions) > 1 and set(conditions) == set(("exit",)):
                        # python: "return [...] missed"
                        conditions = ["loop", "exit"]
                    missing_branches = conditions

                else:
                    # [groovy] embedded conditions
                    conditions = [
                        "%(number)s:%(type)s" % _.attrib
                        for _ in line.iter("condition")
                        if _.attrib.get("coverage") != "100%"
                    ]
                    if handle_missing_conditions:
                        if isinstance(coverage, str):
                            covered_conditions, total_conditions = coverage.split("/")
                            if len(conditions) < int(total_conditions):
                                # <line number="23" hits="0" branch="true" condition-coverage="0% (0/2)">
                                #     <conditions>
                                #         <condition number="0" type="jump" coverage="0%"/>
                                #     </conditions>
                                # </line>

                                # <line number="3" hits="0" branch="true" condition-coverage="50% (1/2)"/>

                                coverage_difference = int(total_conditions) - int(
                                    covered_conditions
                                )
                                missing_condition_elements = range(
                                    len(conditions), coverage_difference
                                )
                                conditions.extend(
                                    [
                                        str(condition)
                                        for condition in missing_condition_elements
                                    ]
                                )
                    else:  # previous behaviour
                        if (
                            isinstance(coverage, str)
                            and coverage[0] == "0"
                            and len(conditions) < int(coverage.split("/")[1])
                        ):
                            # <line number="23" hits="0" branch="true" condition-coverage="0% (0/2)">
                            #     <conditions>
                            #         <condition number="0" type="jump" coverage="0%"/>
                            #     </conditions>
                            # </line>
                            conditions.extend(
                                map(
                                    str,
                                    range(len(conditions), int(coverage.split("/")[1])),
                                )
                            )
                    if conditions:
                        missing_branches = conditions
                if (
                    isinstance(coverage, str)
                    and not coverage[0] == "0"
                    and partials_as_hits
                ):  # if coverage[0] is 0 this is a miss
                    missing_branches = None
                    coverage = 1
                    _type = CoverageType.line

                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(
                        filename=filename,
                        coverage=coverage,
                        coverage_type=_type,
                        missing_branches=missing_branches,
                    ),
                )

        # [scala] [scoverage]
        for stmt in _class.iter("statement"):
            # scoverage will have repeated data
            stmt = stmt.attrib
            if stmt.get("ignored") == "true":
                continue
            coverage = Int(stmt["invocation-count"])
            line_no = int(stmt["line"])
            coverage_type = CoverageType.line
            if stmt["branch"] == "true":
                coverage_type = CoverageType.branch
            elif stmt["method"]:
                coverage_type = CoverageType.method
            
            _file.append(
                line_no,
                report_builder_session.create_coverage_line(
                    filename=filename,
                    coverage=coverage,
                    coverage_type=coverage_type,
                )
            )
        report_builder_session.append(_file)

    # path rename
    path_name_fixing = []
    source_path_list = get_sources_to_attempt(xml)
    for _class in xml.iter("class"):
        filename = _class.attrib["filename"]
        fixed_name = path_fixer(filename, bases_to_try=source_path_list)
        path_name_fixing.append((filename, fixed_name))

    _set = set(("dist-packages", "site-packages"))
    report_builder_session.resolve_paths(
        sorted(path_name_fixing, key=lambda a: _set & set(a[0].split("/")))
    )

    report_builder_session.ignore_lines(ignored_lines)
    return report_builder_session.output_report()
