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

    def test_successful_run(self, transactional_db, mocker, mock_archive_storage):
        mock_logs = mocker.patch("logging.Logger.info")
        archive_value_for_flare = {"some": "data"}
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
            repository=RepositoryFactory(),
        )
        open_pull_with_archive_flare.flare = archive_value_for_flare
        open_pull_with_archive_flare.save()
        open_pull_with_archive_flare.refresh_from_db()
        assert open_pull_with_archive_flare.flare == archive_value_for_flare
        assert open_pull_with_archive_flare._flare is None
        assert open_pull_with_archive_flare._flare_storage_path is not None

        merged_pull_with_archive_flare = PullFactory(
            state=PullStates.MERGED.value,
            _flare=None,
            repository=RepositoryFactory(),
        )
        merged_pull_with_archive_flare.flare = archive_value_for_flare
        merged_pull_with_archive_flare.save()
        merged_pull_with_archive_flare.refresh_from_db()
        assert merged_pull_with_archive_flare.flare == archive_value_for_flare
        assert merged_pull_with_archive_flare._flare is None
        assert merged_pull_with_archive_flare._flare_storage_path is not None

        task = FlareCleanupTask()
        task.manual_run()

        mock_logs.assert_has_calls(
            [
                call("Starting FlareCleanupTask"),
                call("FlareCleanupTask cleared 1 database flares"),
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
        assert open_pull_with_archive_flare._flare_storage_path is not None

        merged_pull_with_archive_flare = Pull.objects.get(
            id=merged_pull_with_archive_flare.id
        )
        assert merged_pull_with_archive_flare.flare == {}
        assert merged_pull_with_archive_flare._flare is None
        assert merged_pull_with_archive_flare._flare_storage_path is None

        mock_logs.reset_mock()
        # check that once these pulls are corrected they are not corrected again
        task = FlareCleanupTask()
        task.manual_run()

        mock_logs.assert_has_calls(
            [
                call("Starting FlareCleanupTask"),
                call("FlareCleanupTask cleared 0 database flares"),
                call("FlareCleanupTask cleared 0 Archive flares"),
            ]
        )

    def test_limits_on_manual_run(self, transactional_db, mocker, mock_archive_storage):
        mock_logs = mocker.patch("logging.Logger.info")
        local_value_for_flare = {"test": "test"}
        archive_value_for_flare = {"some": "data"}

        oldest_to_newest_pulls_with_local_flare = []
        for i in range(5):
            merged_pull_with_local_flare = PullFactory(
                state=PullStates.MERGED.value,
                _flare=local_value_for_flare,
                repository=RepositoryFactory(),
            )
            assert merged_pull_with_local_flare.flare == local_value_for_flare
            assert merged_pull_with_local_flare._flare == local_value_for_flare
            assert merged_pull_with_local_flare._flare_storage_path is None
            oldest_to_newest_pulls_with_local_flare.append(
                merged_pull_with_local_flare.id
            )

        oldest_to_newest_pulls_with_archive_flare = []
        for i in range(5):
            merged_pull_with_archive_flare = PullFactory(
                state=PullStates.MERGED.value,
                _flare=None,
                repository=RepositoryFactory(),
            )
            merged_pull_with_archive_flare.flare = archive_value_for_flare
            merged_pull_with_archive_flare.save()
            assert merged_pull_with_archive_flare.flare == archive_value_for_flare
            assert merged_pull_with_archive_flare._flare is None
            assert merged_pull_with_archive_flare._flare_storage_path is not None
            oldest_to_newest_pulls_with_archive_flare.append(
                merged_pull_with_archive_flare.id
            )

        everything_in_archive_storage = mock_archive_storage.list_folder_contents(
            bucket_name="archive"
        )
        assert len(everything_in_archive_storage) == 5

        task = FlareCleanupTask()
        task.manual_run(limit=3)

        mock_logs.assert_has_calls(
            [
                call("Starting FlareCleanupTask"),
                call("FlareCleanupTask cleared 3 database flares"),
                call("FlareCleanupTask cleared 3 Archive flares"),
            ]
        )

        # there is a cache for flare on the object (all ArchiveFields have this),
        # so get a fresh copy of each object without the cached value
        should_be_cleared = oldest_to_newest_pulls_with_local_flare[:3]
        should_not_be_cleared = oldest_to_newest_pulls_with_local_flare[3:]
        for pull_id in should_be_cleared:
            pull = Pull.objects.get(id=pull_id)
            assert pull.flare == {}
            assert pull._flare is None
            assert pull._flare_storage_path is None

        for pull_id in should_not_be_cleared:
            pull = Pull.objects.get(id=pull_id)
            assert pull.flare == local_value_for_flare
            assert pull._flare == local_value_for_flare
            assert pull._flare_storage_path is None

        everything_in_archive_storage = mock_archive_storage.list_folder_contents(
            bucket_name="archive"
        )
        assert len(everything_in_archive_storage) == 2
        file_names_in_archive_storage = [
            file["name"] for file in everything_in_archive_storage
        ]

        should_be_cleared = oldest_to_newest_pulls_with_archive_flare[:3]
        should_not_be_cleared = oldest_to_newest_pulls_with_archive_flare[3:]
        for pull_id in should_be_cleared:
            pull = Pull.objects.get(id=pull_id)
            assert pull.flare == {}
            assert pull._flare is None
            assert pull._flare_storage_path is None

        for pull_id in should_not_be_cleared:
            pull = Pull.objects.get(id=pull_id)
            assert pull.flare == archive_value_for_flare
            assert pull._flare is None
            assert pull._flare_storage_path is not None
            assert pull._flare_storage_path in file_names_in_archive_storage
