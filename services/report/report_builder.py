import dataclasses
import logging
import typing
from enum import Enum

from shared.reports.resources import LineSession, Report, ReportFile, ReportLine
from shared.reports.types import CoverageDatapoint
from shared.yaml.user_yaml import UserYaml

from helpers.labels import SpecialLabelsEnum

log = logging.getLogger(__name__)


class CoverageType(Enum):
    line = ("line", None)
    branch = ("branch", "b")
    method = ("method", "m")

    def __init__(self, code, report_value):
        self.code = code
        self.report_value = report_value

    def map_to_string(self):
        return self.report_value


class ReportBuilderSession(object):
    def __init__(self, report_builder, report_filepath):
        self._report_builder = report_builder
        self._report_filepath = report_filepath
        self._report = Report()
        self.label_index = {}

    @property
    def file_class(self):
        return self._report.file_class

    @property
    def filepath(self):
        return self._report_filepath

    @property
    def path_fixer(self):
        return self._report_builder.path_fixer

    @property
    def sessionid(self):
        return self._report_builder.sessionid

    @property
    def current_yaml(self):
        return self._report_builder.current_yaml

    @property
    def ignored_lines(self):
        return self._report_builder.ignored_lines

    def ignore_lines(self, *args, **kwargs):
        return self._report.ignore_lines(*args, **kwargs)

    def resolve_paths(self, paths):
        return self._report.resolve_paths(paths)

    def get_file(self, filename):
        return self._report.get(filename)

    def append(self, file):
        return self._report.append(file)

    def output_report(self) -> Report:
        """
            Outputs a Report.
            This function applies all the needed modifications before a report
            can be output

        Returns:
            Report: The legacy report desired
        """
        if len(self.label_index) > 0:
            if len(self.label_index) == 1 and self.label_index.values() == [
                SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER
            ]:
                log.warning(
                    "Report only has SpecialLabels. Might indicate it was not generated with contexts"
                )
            self._report._totals = None
            self._report.set_label_idx(self.label_index)
        return self._report

    def create_coverage_line(
        self,
        filename,
        coverage,
        *,
        coverage_type: CoverageType,
        label_ids_list_of_lists: typing.List[int] = None,
        partials=None,
        missing_branches=None,
        complexity=None
    ) -> ReportLine:
        coverage_type_str = coverage_type.map_to_string()
        datapoints = (
            [
                CoverageDatapoint(
                    sessionid=self.sessionid,
                    coverage=coverage,
                    coverage_type=coverage_type_str,
                    label_ids=label_ids,
                )
                for label_ids in (label_ids_list_of_lists or [[]])
            ]
            if self._report_builder.supports_labels()
            else None
        )
        return ReportLine.create(
            coverage=coverage,
            type=coverage_type_str,
            sessions=[
                (
                    LineSession(
                        id=self.sessionid,
                        coverage=coverage,
                        branches=missing_branches,
                        partials=partials,
                        complexity=complexity,
                    )
                )
            ],
            datapoints=datapoints,
            complexity=complexity,
        )


class ReportBuilder(object):
    def __init__(
        self,
        current_yaml: UserYaml,
        sessionid: int,
        ignored_lines,
        path_fixer: typing.Callable,
    ):
        self.current_yaml = current_yaml
        self.sessionid = sessionid
        self.ignored_lines = ignored_lines
        self.path_fixer = path_fixer

    @property
    def repo_yaml(self) -> UserYaml:
        # small alias for compat purposes
        return self.current_yaml

    def create_report_builder_session(self, filepath) -> ReportBuilderSession:
        return ReportBuilderSession(self, filepath)

    def supports_labels(self) -> bool:
        """Returns wether a report supports labels.
        This is true if the client has configured some flag with carryforward_mode == "labels"
        """
        if self.current_yaml is None or self.current_yaml == {}:
            return False
        old_flag_style = self.current_yaml.get("flags")
        flag_management = self.current_yaml.get("flag_management")
        # Check if some of the old style flags uses labels
        old_flag_with_carryforward_labels = False
        if old_flag_style:
            old_flag_with_carryforward_labels = any(
                map(
                    lambda flag_definition: flag_definition.get("carryforward_mode")
                    == "labels",
                    old_flag_style.values(),
                )
            )
        # Check if some of the flags or default rules use labels
        flag_management_default_rule_carryforward_labels = False
        flag_management_flag_with_carryforward_labels = False
        if flag_management:
            flag_management_default_rule_carryforward_labels = (
                flag_management.get("default_rules", {}).get("carryforward_mode")
                == "labels"
            )
            flag_management_flag_with_carryforward_labels = any(
                map(
                    lambda flag_definition: flag_definition.get("carryforward_mode")
                    == "labels",
                    flag_management.get("individual_flags", []),
                )
            )
        return (
            old_flag_with_carryforward_labels
            or flag_management_default_rule_carryforward_labels
            or flag_management_flag_with_carryforward_labels
        )
