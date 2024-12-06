import json
from unittest.mock import call

from shared.django_apps.core.models import Pull, PullStates
from shared.django_apps.core.tests.factories import PullFactory, RepositoryFactory

from tasks.flare_cleanup import FlareCleanupTask


class TestFlareCleanupTask(object):
    def test_get_min_seconds_interval_between_executions(self):
        assert isinstance(
            FlareCleanupTask.get_min_seconds_interval_between_executions(),
            int,
        )
        assert FlareCleanupTask.get_min_seconds_interval_between_executions() > 17000

    def test_successful_run(self, transactional_db, mocker):
        mock_logs = mocker.patch("logging.Logger.info")
        mock_archive_service = mocker.patch(
            "shared.django_apps.utils.model_utils.ArchiveService"
        )
        archive_value_for_flare = {"some": "data"}
        mock_archive_service.return_value.read_file.return_value = json.dumps(
            archive_value_for_flare
        )
        mock_path = "path/to/written/object"
        mock_archive_service.return_value.write_json_data_to_storage.return_value = (
            mock_path
        )
        mock_archive_service_in_task = mocker.patch(
            "tasks.flare_cleanup.ArchiveService"
        )
        mock_archive_service_in_task.return_value.delete_file.return_value = None

        local_value_for_flare = {"test": "test"}
        open_pull_with_local_flare = PullFactory(
            state=PullStates.OPEN.value,
            _flare=local_value_for_flare,
            repository=RepositoryFactory(),
        )
        assert open_pull_with_local_flare.flare == local_value_for_flare
        assert open_pull_with_local_flare._flare == local_value_for_flare
        assert open_pull_with_local_flare._flare_storage_path is None

        closed_pull_with_local_flare = PullFactory(
            state=PullStates.CLOSED.value,
            _flare=local_value_for_flare,
            repository=RepositoryFactory(),
        )
        assert closed_pull_with_local_flare.flare == local_value_for_flare
        assert closed_pull_with_local_flare._flare == local_value_for_flare
        assert closed_pull_with_local_flare._flare_storage_path is None

        open_pull_with_archive_flare = PullFactory(
            state=PullStates.OPEN.value,
            _flare=None,
            _flare_storage_path=mock_path,
            repository=RepositoryFactory(),
        )
        assert open_pull_with_archive_flare.flare == archive_value_for_flare
        assert open_pull_with_archive_flare._flare is None
        assert open_pull_with_archive_flare._flare_storage_path == mock_path

        merged_pull_with_archive_flare = PullFactory(
            state=PullStates.MERGED.value,
            _flare=None,
            _flare_storage_path=mock_path,
            repository=RepositoryFactory(),
        )
        assert merged_pull_with_archive_flare.flare == archive_value_for_flare
        assert merged_pull_with_archive_flare._flare is None
        assert merged_pull_with_archive_flare._flare_storage_path == mock_path

        task = FlareCleanupTask()
        task.run_cron_task(transactional_db)

        mock_logs.assert_has_calls(
            [
                call("Starting FlareCleanupTask"),
                call("FlareCleanupTask cleared 1 _flares"),
                call("FlareCleanupTask will clear 1 Archive flares"),
                call("FlareCleanupTask cleared 1 Archive flares"),
            ]
        )

        # there is a cache for flare on the object (all ArchiveFields have this),
        # so get a fresh copy of each object without the cached value
        open_pull_with_local_flare = Pull.objects.get(id=open_pull_with_local_flare.id)
        assert open_pull_with_local_flare.flare == local_value_for_flare
        assert open_pull_with_local_flare._flare == local_value_for_flare
        assert open_pull_with_local_flare._flare_storage_path is None

        closed_pull_with_local_flare = Pull.objects.get(
            id=closed_pull_with_local_flare.id
        )
        assert closed_pull_with_local_flare.flare == {}
        assert closed_pull_with_local_flare._flare is None
        assert closed_pull_with_local_flare._flare_storage_path is None

        open_pull_with_archive_flare = Pull.objects.get(
            id=open_pull_with_archive_flare.id
        )
        assert open_pull_with_archive_flare.flare == archive_value_for_flare
        assert open_pull_with_archive_flare._flare is None
        assert open_pull_with_archive_flare._flare_storage_path == mock_path

        merged_pull_with_archive_flare = Pull.objects.get(
            id=merged_pull_with_archive_flare.id
        )
        assert merged_pull_with_archive_flare.flare == {}
        assert merged_pull_with_archive_flare._flare is None
        assert merged_pull_with_archive_flare._flare_storage_path is None

        mock_logs.reset_mock()
        # check that once these pulls are corrected they are not corrected again
        task = FlareCleanupTask()
        task.run_cron_task(transactional_db)

        mock_logs.assert_has_calls(
            [
                call("Starting FlareCleanupTask"),
                call("FlareCleanupTask cleared 0 _flares"),
                call("FlareCleanupTask will clear 0 Archive flares"),
                call("FlareCleanupTask cleared 0 Archive flares"),
            ]
        )
