from database.tests.factories import RepositoryFactory
from services.yaml import track_manual_critical_file_labelling_events
from tests.base import BaseTestCase


class TestYamlTrackingService(BaseTestCase):
    def test_track_manual_critical_file_labelling_addition(self, mocker):
        mocked_tracking_function_add = mocker.patch(
            "services.yaml.track_manual_critical_file_labelling_added_in_YAML"
        )
        mocked_tracking_function_remove = mocker.patch(
            "services.yaml.track_manual_critical_file_labelling_removed_from_YAML"
        )
        existing_yaml = {"profiling": {}}
        new_yaml = {"profiling": {"critical_files_paths": ["/batata.txt"]}}
        repo = RepositoryFactory()
        track_manual_critical_file_labelling_events(existing_yaml, new_yaml, repo)
        mocked_tracking_function_add.assert_called()
        mocked_tracking_function_remove.assert_not_called()

    def test_track_manual_critical_file_labelling_removal(self, mocker):
        mocked_tracking_function_add = mocker.patch(
            "services.yaml.track_manual_critical_file_labelling_added_in_YAML"
        )
        mocked_tracking_function_remove = mocker.patch(
            "services.yaml.track_manual_critical_file_labelling_removed_from_YAML"
        )
        new_yaml = {"profiling": {}}
        existing_yaml = {"profiling": {"critical_files_paths": ["/batata.txt"]}}
        repo = RepositoryFactory()
        track_manual_critical_file_labelling_events(existing_yaml, new_yaml, repo)
        mocked_tracking_function_add.assert_not_called()
        mocked_tracking_function_remove.assert_called()

    def test_track_manual_critical_file_labelling_no_change(self, mocker):
        mocked_tracking_function_add = mocker.patch(
            "services.yaml.track_manual_critical_file_labelling_added_in_YAML"
        )
        mocked_tracking_function_remove = mocker.patch(
            "services.yaml.track_manual_critical_file_labelling_removed_from_YAML"
        )
        yaml_without_paths = {"profiling": {}}
        yaml_with_paths = {"profiling": {"critical_files_paths": ["/batata.txt"]}}
        repo = RepositoryFactory()
        track_manual_critical_file_labelling_events(
            yaml_with_paths, yaml_with_paths, repo
        )
        mocked_tracking_function_add.assert_not_called()
        mocked_tracking_function_remove.assert_not_called()
        track_manual_critical_file_labelling_events(
            yaml_without_paths, yaml_without_paths, repo
        )
        mocked_tracking_function_add.assert_not_called()
        mocked_tracking_function_remove.assert_not_called()
