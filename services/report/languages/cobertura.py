import logging
import re
import typing
from os import path
from typing import List

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from timestring import Date, TimestringInvalid

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder, ReportBuilderSession
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


class CoberturaProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        if bool(list(content.iter("coverage"))):
            return True
        return bool(list(content.iter("scoverage")))

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_xml(content, report_builder_session)


def Int(value):
    try:
        return int(value)
    except ValueError:
        return int(float(value))


def get_sources_to_attempt(xml) -> List[str]:
    sources = [source.text for source in xml.iter("source")]
    return [s for s in sources if isinstance(s, str) and s.startswith("/")]


def from_xml(xml, report_builder_session: ReportBuilderSession) -> Report:
    path_fixer, ignored_lines, sessionid, repo_yaml = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
        report_builder_session.sessionid,
        report_builder_session.current_yaml,
    )

    # # process timestamp
    if read_yaml_field(repo_yaml, ("codecov", "max_report_age"), "12h ago"):
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
            < read_yaml_field(repo_yaml, ("codecov", "max_report_age"), "12h ago")
        ):
            # report expired over 12 hours ago
            raise ReportExpiredException("Cobertura report expired " + timestamp)

    for _class in xml.iter("class"):
        filename = _class.attrib["filename"]
        _file = ReportFile(filename)

        for line in _class.iter("line"):
            _line = line.attrib
            ln = _line["number"]
            if ln == "undefined":
                continue
            ln = int(ln)
            if ln > 0:
                coverage = None
                _type = None
                sessions = None

                # coverage
                branch = _line.get("branch", "")
                condition_coverage = _line.get("condition-coverage", "")
                if (
                    branch == "true"
                    and re.search("\(\d+\/\d+\)", condition_coverage) is not None
                ):
                    coverage = condition_coverage.split(" ", 1)[1][1:-1]  # 1/2
                    _type = "b"
                else:
                    coverage = Int(_line.get("hits"))

                # [python] [scoverage] [groovy] Conditions
                conditions = _line.get("missing-branches", None)
                if conditions:
                    conditions = conditions.split(",")
                    if len(conditions) > 1 and set(conditions) == set(("exit",)):
                        # python: "return [...] missed"
                        conditions = ["loop", "exit"]
                    sessions = [[sessionid, coverage, conditions]]

                else:
                    # [groovy] embedded conditions
                    conditions = [
                        "%(number)s:%(type)s" % _.attrib
                        for _ in line.iter("condition")
                        if _.attrib.get("coverage") != "100%"
                    ]
                    if (
                        type(coverage) is str
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
                                str, range(len(conditions), int(coverage.split("/")[1]))
                            )
                        )
                    if conditions:
                        sessions = [[sessionid, coverage, conditions]]
                _file.append(
                    ln,
                    ReportLine.create(
                        coverage=coverage,
                        type=_type,
                        sessions=sessions or [[sessionid, coverage]],
                    ),
                )

        # [scala] [scoverage]
        for stmt in _class.iter("statement"):
            # scoverage will have repeated data
            stmt = stmt.attrib
            if stmt.get("ignored") == "true":
                continue
            coverage = Int(stmt["invocation-count"])
            if stmt["branch"] == "true":
                _file.append(
                    int(stmt["line"]),
                    ReportLine.create(coverage, "b", [[sessionid, coverage]]),
                )
            else:
                _file.append(
                    int(stmt["line"]),
                    ReportLine.create(
                        coverage,
                        "m" if stmt["method"] else None,
                        [[sessionid, coverage]],
                    ),
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
