import pytest
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitRepoNotFoundError,
)

from database.tests.factories import CommitFactory
from helpers.exceptions import RepositoryWithoutValidBotError
from tasks.commit_update import CommitUpdateTask


@pytest.mark.integration
class TestCommitUpdate(object):
    def test_update_commit(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_redis,
        celery_app,
    ):
        mocker.patch.object(CommitUpdateTask, "app", celery_app)

        commit = CommitFactory.create(
            message="",
            commitid="a2d3e3c30547a000f026daa47610bb3f7b63aece",
            repository__owner__unencrypted_oauth_token="ghp_test3c8iyfspq6h4s9ugpmq19qp7826rv20o",
            repository__owner__username="test-acc9",
            repository__owner__service="github",
            repository__owner__service_id="104562106",
            repository__name="test_example",
            pullid=1,
        )
        dbsession.add(commit)
        dbsession.flush()

        result = CommitUpdateTask().run_impl(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_updated": True}
        assert expected_result == result
        assert commit.message == "random-commit-msg"
        assert commit.parent_commit_id is None
        assert commit.branch == "featureA"
        assert commit.pullid == 1

    def test_update_commit_bot_unauthorized(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
        mock_repo_provider,
        mock_storage,
    ):
        mock_repo_provider.get_commit.side_effect = TorngitClientError(
            401, "response", "message"
        )
        commit = CommitFactory.create(
            message="",
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token="un-authorized",
            repository__owner__username="test-acc9",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
        )
        mock_repo_provider.data = dict(
            repo=dict(repoid=commit.repoid, commit=commit.commitid)
        )
        dbsession.add(commit)
        dbsession.flush()

        result = CommitUpdateTask().run_impl(dbsession, commit.repoid, commit.commitid)
        assert {"was_updated": False} == result
        assert commit.message == ""
        assert commit.parent_commit_id is None

    def test_update_commit_no_bot(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
        mock_repo_provider,
        mock_storage,
    ):
        mock_get_repo_service = mocker.patch(
            "tasks.commit_update.get_repo_provider_service"
        )
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        commit = CommitFactory.create(
            message="",
            parent_commit_id=None,
            commitid="a2d3e3c30547a000f026daa47610bb3f7b63aece",
            repository__owner__unencrypted_oauth_token="ghp_test3c8iyfspq6h4s9ugpmq19qp7826rv20o",
            repository__owner__username="test-acc9",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
            repository__name="test_example",
        )
        dbsession.add(commit)
        dbsession.flush()
        result = CommitUpdateTask().run_impl(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_updated": False}
        assert expected_result == result
        assert commit.message == ""
        assert commit.parent_commit_id is None

    def test_update_commit_repo_not_found(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
        mock_repo_provider,
        mock_storage,
    ):
        mock_get_repo_service = mocker.patch(
            "tasks.commit_update.get_repo_provider_service"
        )
        mock_get_repo_service.side_effect = TorngitRepoNotFoundError(
            "fake_response", "message"
        )
        commit = CommitFactory.create(
            message="",
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token="ghp_test3c8iyfspq6h4s9ugpmq19qp7826rv20o",
            repository__owner__username="test-acc9",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
            repository__name="test_example",
        )
        dbsession.add(commit)
        dbsession.flush()

        result = CommitUpdateTask().run_impl(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_updated": False}
        assert expected_result == result
        assert commit.message == ""
        assert commit.parent_commit_id is None

    def test_update_commit_not_found(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
        mock_repo_provider,
        mock_storage,
    ):
        mock_update_commit_from_provider = mocker.patch(
            "tasks.commit_update.possibly_update_commit_from_provider_info"
        )
        mock_update_commit_from_provider.side_effect = TorngitObjectNotFoundError(
            "fake_response", "message"
        )
        commit = CommitFactory.create(
            message="",
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token="ghp_test3c8iyfspq6h4s9ugpmq19qp7826rv20o",
            repository__owner__username="test-acc9",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
            repository__name="test_example",
        )
        dbsession.add(commit)
        dbsession.flush()

        result = CommitUpdateTask().run_impl(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_updated": False}
        assert expected_result == result
        assert commit.message == ""
        assert commit.parent_commit_id is None

    def test_update_commit_already_populated(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
        mock_repo_provider,
        mock_storage,
    ):
        commit = CommitFactory.create(
            message="commit_msg",
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token="ghp_test3c8iyfspq6h4s9ugpmq19qp7826rv20o",
            repository__owner__username="test-acc9",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
            repository__name="test_example",
        )
        dbsession.add(commit)
        dbsession.flush()

        result = CommitUpdateTask().run_impl(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_updated": False}
        assert expected_result == result
        assert commit.message == "commit_msg"
        assert commit.parent_commit_id is None
