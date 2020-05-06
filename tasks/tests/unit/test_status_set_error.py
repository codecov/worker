import json
import mock
from pathlib import Path

import pytest
from shared.torngit.status import Status

from database.tests.factories import CommitFactory
from tasks.status_set_error import StatusSetErrorTask

here = Path(__file__)


class TestSetErrorTaskUnit(object):
    @pytest.mark.asyncio
    async def test_no_status(self, mocker, mock_configuration, dbsession):
        mocked_1 = mocker.patch("tasks.status_set_error.get_repo_provider_service")
        repo = mocker.MagicMock(
            service="github",
            data=dict(repo=dict(repoid=123)),
            set_commit_status=mock.AsyncMock(return_value=None),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_error.get_current_yaml")
        fetch_current_yaml = {"coverage": {"status": None}}
        mocked_2.return_value = fetch_current_yaml
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        res = await StatusSetErrorTask().run_async(dbsession, repoid, commitid)
        assert not repo.set_commit_status.called
        assert res == {"status_set": False}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "context, cc_status_exists",
        [
            ("patch", True),
            ("project", True),
            ("changes", True),
            ("patch", False),
            ("project", False),
            ("changes", False),
        ],
    )
    async def test_set_error(
        self, context, cc_status_exists, mocker, mock_configuration, dbsession
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
                    "context": "codecov/" + context,
                    "time": "2015-12-21T16:54:13Z",
                }
            ]
            if cc_status_exists
            else []
        )
        get_commit_statuses = Status(statuses)
        set_commit_status = None

        mocked_1 = mocker.patch("tasks.status_set_error.get_repo_provider_service")
        repo = mocker.MagicMock(
            service="github",
            slug="owner/repo",
            token={"username": "bot"},
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mock.AsyncMock(return_value=get_commit_statuses),
            set_commit_status=mock.AsyncMock(return_value=set_commit_status),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_error.get_current_yaml")
        fetch_current_yaml = {
            "coverage": {"status": {context: {"default": {"target": 80}}}}
        }
        mocked_2.return_value = fetch_current_yaml

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        await StatusSetErrorTask().run_async(dbsession, repoid, commitid)
        if cc_status_exists:
            repo.set_commit_status.assert_called_with(
                commit=commitid,
                status="error",
                context="codecov/" + context,
                description="Coverage not measured fully because CI failed",
                url=f"https://codecov.io/gh/owner/repo/commit/{commitid}",
            )
        else:
            assert not repo.set_commit_status.called

    @pytest.mark.asyncio
    async def test_set_error_custom_message(
        self, mocker, mock_configuration, dbsession
    ):
        context = "project"
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
                    "context": "codecov/" + context,
                    "time": "2015-12-21T16:54:13Z",
                }
            ]
        )
        get_commit_statuses = Status(statuses)
        set_commit_status = None

        mocked_1 = mocker.patch("tasks.status_set_error.get_repo_provider_service")
        repo = mocker.MagicMock(
            service="github",
            slug="owner/repo",
            token={"username": "bot"},
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mock.AsyncMock(return_value=get_commit_statuses),
            set_commit_status=mock.AsyncMock(return_value=set_commit_status),
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch("tasks.status_set_error.get_current_yaml")
        fetch_current_yaml = {
            "coverage": {"status": {context: {"default": {"target": 80}}}}
        }
        mocked_2.return_value = fetch_current_yaml

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repoid = commit.repoid
        commitid = commit.commitid
        custom_message = "Uh-oh. This is bad."
        await StatusSetErrorTask().run_async(
            dbsession, repoid, commitid, message=custom_message
        )

        repo.set_commit_status.assert_called_with(
            commit=commitid,
            status="error",
            context="codecov/" + context,
            description=custom_message,
            url=f"https://codecov.io/gh/owner/repo/commit/{commitid}",
        )
