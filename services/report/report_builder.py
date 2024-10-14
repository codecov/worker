import logging
from enum import Enum
from typing import Any, Sequence

from shared.reports.resources import LineSession, Report, ReportFile, ReportLine
from shared.yaml.user_yaml import UserYaml

from services.path_fixer import PathFixer
from services.yaml.reader import read_yaml_field

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
    def __init__(
        self,
        report_builder: "ReportBuilder",
        report_filepath: str,
    ):
        self.filepath = report_filepath
        self._report_builder = report_builder
        self._report = Report()

    @property
    def path_fixer(self):
        return self._report_builder.path_fixer

    def resolve_paths(self, paths):
        return self._report.resolve_paths(paths)

    def yaml_field(self, keys: Sequence[str], default: Any = None) -> Any:
        return read_yaml_field(self._report_builder.current_yaml, keys, default)

    def get_file(self, filename: str) -> ReportFile | None:
        return self._report.get(filename)

    def append(self, file: ReportFile):
        return self._report.append(file)

    def output_report(self) -> Report:
        return self._report

    def create_coverage_file(
        self, path: str, do_fix_path: bool = True
    ) -> ReportFile | None:
        fixed_path = self._report_builder.path_fixer(path) if do_fix_path else path
        if not fixed_path:
            return None

        return ReportFile(
            fixed_path, ignore=self._report_builder.ignored_lines.get(fixed_path)
        )

    def create_coverage_line(
        self,
        coverage: int | str,
        coverage_type: CoverageType | None = None,
        partials=None,
        missing_branches=None,
        complexity=None,
    ) -> ReportLine:
        sessionid = self._report_builder.sessionid
        coverage_type_str = coverage_type.map_to_string() if coverage_type else None
        return ReportLine.create(
            coverage=coverage,
            type=coverage_type_str,
            sessions=[
                (
                    LineSession(
                        id=sessionid,
                        coverage=coverage,
                        branches=missing_branches,
                        partials=partials,
                        complexity=complexity,
                    )
                )
            ],
            complexity=complexity,
        )


class ReportBuilder(object):
    def __init__(
        self,
        current_yaml: UserYaml,
        sessionid: int,
        ignored_lines: dict,
        path_fixer: PathFixer,
    ):
        self.current_yaml = current_yaml
        self.sessionid = sessionid
        self.ignored_lines = ignored_lines
        self.path_fixer = path_fixer

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
