from pathlib import Path

import mock
import pytest
from shared.torngit.status import Status

from database.tests.factories import CommitFactory
from tasks.status_set_pending import StatusSetPendingTask

here = Path(__file__)


class TestSetPendingTaskUnit(object):
    def test_no_status(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch("tasks.status_set_pending.get_repo_provider_service")
        repo = mocker.MagicMock(
            service="github",
            data=dict(repo=dict(repoid=123)),
            set_commit_status=mock.AsyncMock(return_value=None),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_pending.get_current_yaml")
        fetch_current_yaml = {"coverage": {"status": None}}
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        branch = "master"
        on_a_pull_request = False
        res = StatusSetPendingTask().run_impl(
            dbsession, repoid, commitid, branch, on_a_pull_request
        )
        assert res["status_set"] == False
        assert not repo.set_commit_status.called

    def test_not_in_beta(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch("tasks.status_set_pending.get_repo_provider_service")
        repo = mocker.MagicMock(
            service="github",
            data=dict(repo=dict(repoid=123)),
            set_commit_status=mock.AsyncMock(return_value=None),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_pending.get_current_yaml")
        fetch_current_yaml = {"coverage": {"status": None}}
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [False]

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        branch = "master"
        on_a_pull_request = False
        with pytest.raises(
            AssertionError, match="Pending disabled. Please request to be in beta."
        ):
            StatusSetPendingTask().run_impl(
                dbsession, repoid, commitid, branch, on_a_pull_request
            )
        mock_redis.sismember.assert_called_with("beta.pending", repoid)

    def test_skip_set_pending(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch("tasks.status_set_pending.get_repo_provider_service")
        get_commit_statuses = Status([])
        set_commit_status = None
        repo = mocker.MagicMock(
            service="github",
            slug="owner/repo",
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mock.AsyncMock(return_value=get_commit_statuses),
            set_commit_status=mock.AsyncMock(return_value=set_commit_status),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_pending.get_current_yaml")
        fetch_current_yaml = {
            "coverage": {
                "status": {"project": {"custom": {"target": 80, "set_pending": False}}}
            }
        }
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        branch = "master"
        on_a_pull_request = False
        res = StatusSetPendingTask().run_impl(
            dbsession, repoid, commitid, branch, on_a_pull_request
        )
        assert not repo.set_commit_status.called
        assert res["status_set"] == False

    def test_skip_set_pending_unknown_branch(
        self, mocker, mock_configuration, dbsession, mock_redis
    ):
        mocked_1 = mocker.patch("tasks.status_set_pending.get_repo_provider_service")
        get_commit_statuses = Status([])
        set_commit_status = None
        repo = mocker.MagicMock(
            service="github",
            slug="owner/repo",
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mock.AsyncMock(return_value=get_commit_statuses),
            set_commit_status=mock.AsyncMock(return_value=set_commit_status),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_pending.get_current_yaml")
        fetch_current_yaml = {
            "coverage": {
                "status": {
                    "project": {"custom": {"target": 80, "branches": ["master"]}}
                }
            }
        }
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        branch = None
        on_a_pull_request = False
        res = StatusSetPendingTask().run_impl(
            dbsession, repoid, commitid, branch, on_a_pull_request
        )
        assert not repo.set_commit_status.called
        assert res["status_set"] == False

    @pytest.mark.parametrize(
        "context, branch, cc_status_exists",
        [
            ("patch", "master", False),
            ("patch", "master", False),
            ("patch", "master", True),
            ("patch", "skip", False),
            ("project", "master", False),
            ("project", "skip", False),
            ("project", "master", True),
            ("changes", "master", False),
            ("changes", "master", False),
            ("changes", "master", True),
            ("changes", "skip", False),
        ],
    )
    def test_set_pending(
        self,
        context,
        branch,
        cc_status_exists,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
    ):
        statuses = [
            {
                "url": None,
                "state": "pending",
                "context": "ci",
                "time": "2015-12-21T16:54:13Z",
            }
        ] + (
            [
                {
                    "url": None,
                    "state": "pending",
                    "context": "codecov/" + context + "/custom",
                    "time": "2015-12-21T16:54:13Z",
                }
            ]
            if cc_status_exists
            else []
        )

        mocked_1 = mocker.patch("tasks.status_set_pending.get_repo_provider_service")
        get_commit_statuses = Status(statuses)
        set_commit_status = None
        repo = mocker.MagicMock(
            service="github",
            slug="owner/repo",
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mock.AsyncMock(return_value=get_commit_statuses),
            set_commit_status=mock.AsyncMock(return_value=set_commit_status),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_pending.get_current_yaml")
        fetch_current_yaml = {
            "coverage": {
                "status": {context: {"custom": {"target": 80, "branches": ["!skip"]}}}
            }
        }
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        on_a_pull_request = False
        StatusSetPendingTask().run_impl(
            dbsession, repoid, commitid, branch, on_a_pull_request
        )
        if branch == "master" and not cc_status_exists:
            repo.set_commit_status.assert_called_with(
                commitid,
                "pending",
                "codecov/" + context + "/custom",
                "Collecting reports and waiting for CI to complete",
                f"https://codecov.io/gh/owner/repo/commit/{commitid}",
            )
        else:
            assert not repo.set_commit_status.called
