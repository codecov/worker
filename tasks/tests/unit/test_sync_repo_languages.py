from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from shared.torngit.exceptions import TorngitError
from shared.utils.enums import TaskConfigGroup

from database.tests.factories.core import OwnerFactory, RepositoryFactory
from tasks.sync_repo_languages import SyncRepoLanguagesTask

MOCKED_NOW = datetime(2024, 7, 3, 6, 8, 12)
LIST_WITH_INTERSECTION = ["python", "go", "javascript"]


def setup_now(mocker):
    mocker.patch(
        f"tasks.{TaskConfigGroup.sync_repo_languages.value}.get_utc_now",
        return_value=MOCKED_NOW,
    )


@pytest.fixture
def setup_with_languages(mocker, mock_repo_provider):
    setup_now(mocker)

    mock_repo_provider.get_repo_languages.return_value = LIST_WITH_INTERSECTION
    mocker.patch(
        "tasks.base.get_repo_provider_service",
        return_value=mock_repo_provider,
    )


@pytest.fixture
def setup_with_null_languages(mocker, mock_repo_provider):
    setup_now(mocker)

    mock_repo_provider.get_repo_languages.return_value = None
    mocker.patch(
        "tasks.base.get_repo_provider_service",
        return_value=mock_repo_provider,
    )


@pytest.fixture
def setup_with_languages_bitbucket(mocker, mock_repo_provider):
    setup_now(mocker)

    mock_repo_provider.get_repo_languages.return_value = ["javascript"]
    mocker.patch(
        "tasks.base.get_repo_provider_service",
        return_value=mock_repo_provider,
    )


@pytest.fixture
def setup_with_torngit_error(mocker, mock_repo_provider):
    setup_now(mocker)

    mock_repo_provider.get_repo_languages = Mock(side_effect=TorngitError())


class TestSyncRepoLanguages(object):
    def test_languages_no_intersection_and_not_synced_github(
        self, dbsession, setup_with_languages
    ):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        repo = RepositoryFactory.create(
            owner=owner, languages_last_updated=None, languages=[]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True
        }
        assert repo.languages == LIST_WITH_INTERSECTION
        assert repo.languages_last_updated == MOCKED_NOW

    def test_languages_no_intersection_and_not_synced_gitlab(
        self, dbsession, setup_with_languages
    ):
        owner = OwnerFactory.create(service="gitlab")
        dbsession.add(owner)
        repo = RepositoryFactory.create(
            owner=owner, languages_last_updated=None, languages=[]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True
        }
        assert repo.languages == LIST_WITH_INTERSECTION
        assert repo.languages_last_updated == MOCKED_NOW

    def test_languages_no_intersection_and_not_synced_bitbucket(
        self, dbsession, setup_with_languages_bitbucket
    ):
        owner = OwnerFactory.create(service="bitbucket")
        dbsession.add(owner)
        repo = RepositoryFactory.create(
            owner=owner,
            languages_last_updated=None,
            languages=[],
            language="javascript",
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True
        }
        assert repo.languages == ["javascript"]
        assert repo.languages_last_updated == MOCKED_NOW

    def test_languages_no_intersection_and_synced_below_threshold(
        self, dbsession, setup_with_languages
    ):
        mocked_below_threshold = MOCKED_NOW + timedelta(days=-3)

        repo = RepositoryFactory.create(
            languages_last_updated=mocked_below_threshold, languages=[]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True,
            "synced": False,
        }

    def test_languages_no_intersection_and_synced_beyond_threshold(
        self, dbsession, setup_with_languages
    ):
        mocked_beyond_threshold = MOCKED_NOW + timedelta(days=-10)

        repo = RepositoryFactory.create(
            languages_last_updated=mocked_beyond_threshold, languages=[]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True
        }
        assert repo.languages == LIST_WITH_INTERSECTION
        assert repo.languages_last_updated == MOCKED_NOW

    def test_languages_intersection_and_synced_below_threshold(
        self, dbsession, setup_with_languages
    ):
        mocked_below_threshold = MOCKED_NOW + timedelta(days=-3)

        repo = RepositoryFactory.create(
            languages_last_updated=mocked_below_threshold, languages=["javascript"]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True,
            "synced": False,
        }

    def test_languages_intersection_and_synced_beyond_threshold(
        self, dbsession, setup_with_null_languages
    ):
        mocked_beyond_threshold = MOCKED_NOW + timedelta(days=-10)

        repo = RepositoryFactory.create(
            languages_last_updated=mocked_beyond_threshold, languages=["javascript"]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True,
            "synced": False,
        }

    def test_languages_intersection_and_synced_beyond_threshold_with_languages(
        self, dbsession, setup_with_languages
    ):
        mocked_beyond_threshold = MOCKED_NOW + timedelta(days=-10)

        repo = RepositoryFactory.create(
            languages_last_updated=mocked_beyond_threshold, languages=["javascript"]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=False) == {
            "successful": True,
            "synced": False,
        }

    def test_languages_intersection_and_synced_with_manual_trigger(
        self, dbsession, setup_with_languages
    ):
        mocked_beyond_threshold = MOCKED_NOW + timedelta(days=-10)

        repo = RepositoryFactory.create(
            languages_last_updated=mocked_beyond_threshold, languages=["javascript"]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=True) == {
            "successful": True
        }
        assert repo.languages == LIST_WITH_INTERSECTION
        assert repo.languages_last_updated == MOCKED_NOW

    def test_languages_torngit_error(self, dbsession, setup_with_torngit_error):
        repo = RepositoryFactory.create(
            languages_last_updated=None, languages=["javascript"]
        )
        dbsession.add(repo)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        res = task.run_impl(dbsession, repoid=repo.repoid, manual_trigger=True)
        assert res["successful"] == False
        assert res["error"] == "no_repo_in_provider"

    def test_languages_no_repository(self, dbsession):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()

        task = SyncRepoLanguagesTask()
        assert task.run_impl(dbsession, repoid=123, manual_trigger=False) == {
            "successful": False,
            "error": "no_repo_in_db",
        }
