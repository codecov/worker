import json
import logging
import typing

from shared.storage.exceptions import FileNotInStorageError

from database.models.staticanalysis import (
    StaticAnalysisSingleFileSnapshot,
    StaticAnalysisSuite,
    StaticAnalysisSuiteFilepath,
)
from services.archive import ArchiveService
from services.static_analysis.git_diff_parser import DiffChange, DiffChangeType
from services.static_analysis.single_file_analyzer import (
    AntecessorFindingResult,
    SingleFileSnapshotAnalyzer,
)

log = logging.getLogger(__name__)


def _get_analysis_content_mapping(analysis: StaticAnalysisSuite, filepaths):
    db_session = analysis.get_db_session()
    return dict(
        db_session.query(
            StaticAnalysisSuiteFilepath.filepath,
            StaticAnalysisSingleFileSnapshot.content_location,
        )
        .join(
            StaticAnalysisSuiteFilepath,
            StaticAnalysisSuiteFilepath.file_snapshot_id
            == StaticAnalysisSingleFileSnapshot.id_,
        )
        .filter(
            StaticAnalysisSuiteFilepath.filepath.in_(filepaths),
            StaticAnalysisSuiteFilepath.analysis_suite_id == analysis.id_,
        )
    )


class StaticAnalysisComparisonService(object):
    def __init__(
        self,
        base_static_analysis: StaticAnalysisSuite,
        head_static_analysis: StaticAnalysisSuite,
        git_diff: typing.List[DiffChange],
    ):
        self._base_static_analysis = base_static_analysis
        self._head_static_analysis = head_static_analysis
        self._git_diff = git_diff
        self._archive_service = None

    @property
    def archive_service(self):
        if self._archive_service is None:
            self._archive_service = ArchiveService(
                self._base_static_analysis.commit.repository
            )
        return self._archive_service

    def get_base_lines_relevant_to_change(self) -> typing.List[typing.Dict]:
        final_result = {"all": False, "files": {}}
        db_session = self._base_static_analysis.get_db_session()
        head_analysis_content_locations_mapping = _get_analysis_content_mapping(
            self._head_static_analysis,
            [
                change.after_filepath
                for change in self._git_diff
                if change.after_filepath
            ],
        )
        base_analysis_content_locations_mapping = _get_analysis_content_mapping(
            self._head_static_analysis,
            [
                change.before_filepath
                for change in self._git_diff
                if change.before_filepath
            ],
        )
        for change in self._git_diff:
            if change.change_type == DiffChangeType.new:
                return {"all": True}
            assert change.before_filepath
            final_result["files"][change.before_filepath] = self._analyze_single_change(
                db_session,
                change,
                base_analysis_content_locations_mapping.get(change.before_filepath),
                head_analysis_content_locations_mapping.get(change.after_filepath),
            )
        return final_result

    def _load_snapshot_data(
        self, filepath, content_location
    ) -> typing.Optional[SingleFileSnapshotAnalyzer]:
        if not content_location:
            return None
        try:
            return SingleFileSnapshotAnalyzer(
                filepath,
                json.loads(self.archive_service.read_file(content_location)),
            )
        except FileNotInStorageError:
            log.warning(
                "Unable to load file for static analysis comparison",
                extra=dict(filepath=filepath, content_location=content_location),
            )
            return None

    def _analyze_single_change(
        self,
        db_session,
        change: DiffChange,
        base_analysis_file_obj_content_location,
        head_analysis_file_obj_content_location,
    ):
        if change.change_type == DiffChangeType.deleted:
            # file simply deleted.
            # all lines involved in it needs their tests rechecked
            return {"all": True, "lines": None}
        if change.change_type == DiffChangeType.modified:
            result_so_far = {"all": False, "lines": set()}
            head_analysis_file_data = self._load_snapshot_data(
                change.after_filepath, head_analysis_file_obj_content_location
            )
            base_analysis_file_data = self._load_snapshot_data(
                change.before_filepath, base_analysis_file_obj_content_location
            )
            if not head_analysis_file_data and not base_analysis_file_data:
                return None
            for base_line in change.lines_only_on_base:
                result_so_far["lines"].add(
                    base_analysis_file_data.get_corresponding_executable_line(base_line)
                )
            affected_statement_lines = set(
                [
                    head_analysis_file_data.get_corresponding_executable_line(li)
                    for li in change.lines_only_on_head
                ]
            )
            for head_line in affected_statement_lines:
                (
                    matching_type,
                    antecessor_head_line,
                ) = head_analysis_file_data.get_antecessor_executable_line(
                    head_line, lines_to_not_consider=affected_statement_lines
                )
                if matching_type == AntecessorFindingResult.file:
                    return {"all": True, "lines": None}
                elif matching_type == AntecessorFindingResult.function:
                    matching_function = (
                        base_analysis_file_data.find_function_by_identifier(
                            antecessor_head_line
                        )
                    )
                    if matching_function:
                        line_entrypoint = matching_function["start_line"]
                        result_so_far["lines"].add(line_entrypoint)
                    else:
                        # No matches, function does not exist on base, go to everything
                        return {"all": True, "lines": None}
                elif matching_type == AntecessorFindingResult.line:
                    result_so_far["lines"].add(antecessor_head_line)
            return result_so_far
