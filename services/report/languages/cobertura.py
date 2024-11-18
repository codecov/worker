import logging
import re
from typing import Sequence

import sentry_sdk
from lxml.etree import Element
from timestring import Date, TimestringInvalid

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession

log = logging.getLogger(__name__)


class CoberturaProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag in ("coverage", "scoverage")

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def Int(value):
    try:
        return int(value)
    except ValueError:
        return int(float(value))


def get_sources_to_attempt(xml) -> Sequence[str]:
    sources = (source.text for source in xml.iter("source"))
    return tuple(s for s in sources if isinstance(s, str) and s.startswith("/"))


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    # # process timestamp
    if max_age := report_builder_session.yaml_field(
        ("codecov", "max_report_age"), "12h ago"
    ):
        try:
            timestamp = xml.get("timestamp")
            parsed_datetime = Date(timestamp)
            is_valid_timestamp = True
        except TimestringInvalid:
            parsed_datetime = None
            is_valid_timestamp = False

        if timestamp and is_valid_timestamp and parsed_datetime < max_age:
            # report expired over 12 hours ago
            raise ReportExpiredException("Cobertura report expired " + timestamp)

    handle_missing_conditions = report_builder_session.yaml_field(
        ("parsers", "cobertura", "handle_missing_conditions"),
        False,
    )
    partials_as_hits = report_builder_session.yaml_field(
        ("parsers", "cobertura", "partials_as_hits"),
        False,
    )

    for _class in xml.iter("class"):
        filename = _class.attrib["filename"]
        if not filename:
            continue
        _file = report_builder_session.create_coverage_file(filename, do_fix_path=False)
        assert (
            _file is not None
        ), "`create_coverage_file` with pre-fixed path is infallible"

        for line in _class.iter("line"):
            _line = line.attrib
            ln: str | int = _line["number"]
            if ln == "undefined":
                continue
            ln = int(ln)
            if ln > 0:
                coverage: str | int
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
                conditions_text = _line.get("missing-branches", None)
                if conditions_text:
                    conditions = conditions_text.split(",")
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
                        coverage,
                        _type,
                        missing_branches=missing_branches,
                    ),
                )

        # [scala] [scoverage]
        for stmt in _class.iter("statement"):
            # scoverage will have repeated data
            attr = stmt.attrib
            if attr.get("ignored") == "true":
                continue
            coverage = Int(attr["invocation-count"])
            line_no = int(attr["line"])
            coverage_type = CoverageType.line
            if attr["branch"] == "true":
                coverage_type = CoverageType.branch
            elif attr["method"]:
                coverage_type = CoverageType.method

            _file.append(
                line_no,
                report_builder_session.create_coverage_line(
                    coverage,
                    coverage_type,
                ),
            )
        report_builder_session.append(_file)

    # path rename
    path_fixer = report_builder_session.path_fixer
    source_path_list = get_sources_to_attempt(xml)
    path_name_fixing = []

    for _class in xml.iter("class"):
        filename = _class.attrib["filename"]
        fixed_name = path_fixer(filename, bases_to_try=source_path_list)
        path_name_fixing.append((filename, fixed_name))

    # paths with `X-packages` should be sorted to the end
    path_name_fixing.sort(
        key=lambda a: "/dist-packages/" in a[0] or "/site-packages/" in a[0]
    )

    report_builder_session.resolve_paths(path_name_fixing)
