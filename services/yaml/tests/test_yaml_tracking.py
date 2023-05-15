from database.tests.factories import RepositoryFactory
from services.yaml.tracking import (
    _track_manual_critical_file_labelling_events,
    _was_betaprofiling_added_in_yaml,
    _was_betaprofiling_removed_from_yaml,
    tracking_yaml_fields_changes,
)
from test_utils.base import BaseTestCase


class TestYamlTrackingService(BaseTestCase):
    def test_added_betaprofiling(self, mocker):
        existing_comment_sec = ["reach", "diff", "flags", "files", "footer"]
        new_comment_sec = ["reach", "diff", "flags", "files", "betaprofiling", "footer"]
        assert _was_betaprofiling_added_in_yaml(existing_comment_sec, new_comment_sec)

    def test_removed_betaprofiling(self, mocker):
        existing_comment_sec = [
            "reach",
            "diff",
            "flags",
            "files",
            "betaprofiling",
            "footer",
        ]
        new_comment_sec = ["reach", "diff", "flags", "files", "footer"]
        assert _was_betaprofiling_removed_from_yaml(
            existing_comment_sec, new_comment_sec
        )

    def test_no_change_in_yaml(self, mocker):
        existing_comment_sec = [
            "reach",
            "diff",
            "flags",
            "files",
            "betaprofiling",
            "footer",
        ]
        new_comment_sec = ["reach", "diff", "flags", "files", "betaprofiling", "footer"]
        assert not _was_betaprofiling_removed_from_yaml(
            existing_comment_sec, new_comment_sec
        )
        assert not _was_betaprofiling_added_in_yaml(
            existing_comment_sec, new_comment_sec
        )

    def test_tracking_added_betaprofling(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {"comment": {"layout": "reach ,diff, flags, files, footer"}}
        new_yaml = {
            "comment": {"layout": "reach ,diff, flags, betaprofiling, files, footer"}
        }
        mocked_betaprofiling_added_segment_track = mocker.patch(
            "services.yaml.tracking.track_betaprofiling_added_in_YAML"
        )
        tracking_yaml_fields_changes(existing_yaml, new_yaml, repo)
        mocked_betaprofiling_added_segment_track.assert_called_once()

    def test_tracking_removed_betaprofling(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {
            "comment": {"layout": "reach ,diff,betaprofiling, flags, files, footer"}
        }
        new_yaml = {"comment": {"layout": "reach ,diff, flags, files, footer"}}
        mocked_betaprofiling_removed_segment_track = mocker.patch(
            "services.yaml.tracking.track_betaprofiling_removed_from_YAML"
        )
        tracking_yaml_fields_changes(existing_yaml, new_yaml, repo)
        mocked_betaprofiling_removed_segment_track.assert_called_once()

    def test_tracking_added_show_critical_paths(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {"comment": ""}
        new_yaml = {"comment": {"show_critical_paths": True}}
        mocked_show_critical_paths_added_segment_track = mocker.patch(
            "services.yaml.tracking.track_show_critical_paths_added_in_YAML"
        )
        tracking_yaml_fields_changes(existing_yaml, new_yaml, repo)
        mocked_show_critical_paths_added_segment_track.assert_called_once()

    def test_tracking_removed_show_critical_paths(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {"comment": {"show_critical_paths": True}}
        new_yaml = {"comment": ""}
        mocked_show_critical_paths_removed_segment_track = mocker.patch(
            "services.yaml.tracking.track_show_critical_paths_removed_from_YAML"
        )
        tracking_yaml_fields_changes(existing_yaml, new_yaml, repo)
        mocked_show_critical_paths_removed_segment_track.assert_called_once()

    def test_track_manual_critical_file_labelling_addition(self, mocker):
        mocked_tracking_function_add = mocker.patch(
            "services.yaml.tracking.track_manual_critical_file_labelling_added_in_YAML"
        )
        mocked_tracking_function_remove = mocker.patch(
            "services.yaml.tracking.track_manual_critical_file_labelling_removed_from_YAML"
        )
        existing_yaml = {"profiling": {}}
        new_yaml = {"profiling": {"critical_files_paths": ["/batata.txt"]}}
        repo = RepositoryFactory()
        _track_manual_critical_file_labelling_events(existing_yaml, new_yaml, repo)
        mocked_tracking_function_add.assert_called()
        mocked_tracking_function_remove.assert_not_called()

    def test_track_manual_critical_file_labelling_removal(self, mocker):
        mocked_tracking_function_add = mocker.patch(
            "services.yaml.tracking.track_manual_critical_file_labelling_added_in_YAML"
        )
        mocked_tracking_function_remove = mocker.patch(
            "services.yaml.tracking.track_manual_critical_file_labelling_removed_from_YAML"
        )
        new_yaml = {"profiling": {}}
        existing_yaml = {"profiling": {"critical_files_paths": ["/batata.txt"]}}
        repo = RepositoryFactory()
        _track_manual_critical_file_labelling_events(existing_yaml, new_yaml, repo)
        mocked_tracking_function_add.assert_not_called()
        mocked_tracking_function_remove.assert_called()

    def test_track_manual_critical_file_labelling_no_change(self, mocker):
        mocked_tracking_function_add = mocker.patch(
            "services.yaml.tracking.track_manual_critical_file_labelling_added_in_YAML"
        )
        mocked_tracking_function_remove = mocker.patch(
            "services.yaml.tracking.track_manual_critical_file_labelling_removed_from_YAML"
        )
        yaml_without_paths = {"profiling": {}}
        yaml_with_paths = {"profiling": {"critical_files_paths": ["/batata.txt"]}}
        repo = RepositoryFactory()
        _track_manual_critical_file_labelling_events(
            yaml_with_paths, yaml_with_paths, repo
        )
        mocked_tracking_function_add.assert_not_called()
        mocked_tracking_function_remove.assert_not_called()
        _track_manual_critical_file_labelling_events(
            yaml_without_paths, yaml_without_paths, repo
        )
        mocked_tracking_function_add.assert_not_called()
        mocked_tracking_function_remove.assert_not_called()
