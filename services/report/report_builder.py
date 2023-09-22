import dataclasses
import typing
from enum import Enum

from shared.reports.resources import LineSession, Report, ReportFile, ReportLine
from shared.reports.types import CoverageDatapoint
from shared.yaml.user_yaml import UserYaml

from helpers.labels import SpecialLabelsEnum


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
        self._present_labels = set()

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
        if file is not None:
            for line_number, line in file.lines:
                if line.datapoints:
                    for datapoint in line.datapoints:
                        if datapoint.labels:
                            for label in datapoint.labels:
                                self._present_labels.add(label)
        return self._report.append(file)

    def output_report(self) -> Report:
        """
            Outputs a Report.
            This function applies all the needed modifications before a report
            can be output

        Returns:
            Report: The legacy report desired
        """
        if self._present_labels:
            for file in self._report:
                for line_number, line in file.lines:
                    self._possibly_modify_line_to_account_for_special_labels(
                        file, line_number, line
                    )
            self._report._totals = None
        return self._report

    def _possibly_modify_line_to_account_for_special_labels(
        self, file: ReportFile, line_number: int, line: ReportLine
    ) -> None:
        """Possibly modify the report line in the file
        to account for any label in the SpecialLabelsEnum

        Args:
            file (ReportFile): The file we want to modify
            line_number (int): The line number in case we
                need to set the new line back into the files
            line (ReportLine): The original line
        """
        new_datapoints = []
        if line.datapoints:
            new_datapoints = [
                self._possibly_convert_datapoints(datapoint)
                for datapoint in line.datapoints
            ]
            new_datapoints = [item for dp_list in new_datapoints for item in dp_list]
            if new_datapoints and new_datapoints != line.datapoints:
                # A check to avoid unnecessary replacement
                file[line_number] = dataclasses.replace(
                    line,
                    datapoints=sorted(
                        new_datapoints,
                        key=lambda x: (
                            x.sessionid,
                            x.coverage,
                            x.coverage_type,
                        ),
                    ),
                )
                file._totals = None

    def _possibly_convert_datapoints(
        self, datapoint: CoverageDatapoint
    ) -> typing.List[CoverageDatapoint]:
        """Possibly convert datapoints
            The datapoint that might need to be converted

        Args:
            datapoint (CoverageDatapoint): The datapoint to convert
        """
        if datapoint.labels and any(
            label == SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER
            for label in datapoint.labels
        ):
            new_label = (
                SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label
            )
            return [
                dataclasses.replace(
                    datapoint,
                    labels=sorted(
                        set(
                            [
                                label
                                for label in datapoint.labels
                                if label
                                != SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER
                            ]
                            + [new_label]
                        )
                    ),
                )
            ]
        return [datapoint]

    def create_coverage_line(
        self,
        filename,
        coverage,
        *,
        coverage_type: CoverageType,
        labels_list_of_lists: typing.List[typing.Union[str, SpecialLabelsEnum]] = None,
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
                    labels=labels,
                )
                for labels in (labels_list_of_lists or [[]])
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
