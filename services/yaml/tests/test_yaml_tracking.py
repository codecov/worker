from database.tests.factories import RepositoryFactory
from services.yaml import (
    betaprofiling_is_added_in_yaml,
    betaprofiling_is_removed_from_yaml,
    tracking_runtime_insights_fields,
)
from tests.base import BaseTestCase


class TestYamlTrackingService(BaseTestCase):
    def test_added_betaprofiling(self, mocker):
        existing_comment_sec = ["reach", "diff", "flags", "files", "footer"]
        new_comment_sec = ["reach", "diff", "flags", "files", "betaprofiling", "footer"]
        assert betaprofiling_is_added_in_yaml(existing_comment_sec, new_comment_sec)

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
        assert betaprofiling_is_removed_from_yaml(existing_comment_sec, new_comment_sec)

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
        assert not betaprofiling_is_removed_from_yaml(
            existing_comment_sec, new_comment_sec
        )
        assert not betaprofiling_is_added_in_yaml(existing_comment_sec, new_comment_sec)

    def test_tracking_added_betaprofling(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {"comment": {"layout": "reach ,diff, flags, files, footer"}}
        new_yaml = {
            "comment": {"layout": "reach ,diff, flags, betaprofiling, files, footer"}
        }
        mocked_betaprofiling_added_segment_track = mocker.patch(
            "services.yaml.track_betaprofiling_added_in_YAML"
        )
        tracking_runtime_insights_fields(existing_yaml, new_yaml, repo)
        mocked_betaprofiling_added_segment_track.assert_called_once()

    def test_tracking_removed_betaprofling(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {
            "comment": {"layout": "reach ,diff,betaprofiling, flags, files, footer"}
        }
        new_yaml = {"comment": {"layout": "reach ,diff, flags, files, footer"}}
        mocked_betaprofiling_removed_segment_track = mocker.patch(
            "services.yaml.track_betaprofiling_removed_from_YAML"
        )
        tracking_runtime_insights_fields(existing_yaml, new_yaml, repo)
        mocked_betaprofiling_removed_segment_track.assert_called_once()

    def test_tracking_added_show_critical_paths(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {"comment": ""}
        new_yaml = {"comment": {"show_critical_paths": True}}
        mocked_show_critical_paths_added_segment_track = mocker.patch(
            "services.yaml.track_show_critical_paths_added_in_YAML"
        )
        tracking_runtime_insights_fields(existing_yaml, new_yaml, repo)
        mocked_show_critical_paths_added_segment_track.assert_called_once()

    def test_tracking_removed_show_critical_paths(self, mocker):
        repo = RepositoryFactory.create()
        existing_yaml = {"comment": {"show_critical_paths": True}}
        new_yaml = {"comment": ""}
        mocked_show_critical_paths_removed_segment_track = mocker.patch(
            "services.yaml.track_show_critical_paths_removed_from_YAML"
        )
        tracking_runtime_insights_fields(existing_yaml, new_yaml, repo)
        mocked_show_critical_paths_removed_segment_track.assert_called_once()
