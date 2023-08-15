import asyncio
import datetime
import uuid

import httpx
import pytest
import respx
from mock import Mock, patch

from database.models import Constants
from database.tests.factories import (
    CommitFactory,
    ConstantsFactory,
    RepositoryFactory,
    UploadFactory,
    UserFactory,
)
from tasks.brolly_stats_rollup import DEFAULT_BROLLY_ENDPOINT, BrollyStatsRollupTask


def _get_n_hours_ago(n):
    return datetime.datetime.now() - datetime.timedelta(hours=n)


def _mock_response():
    f = asyncio.Future()
    f.set_result = Mock(status_code=200)
    return f


class TestBrollyStatsRollupTask(object):
    @pytest.mark.asyncio
    async def test_get_min_seconds_interval_between_executions(self, dbsession):
        assert isinstance(
            BrollyStatsRollupTask.get_min_seconds_interval_between_executions(),
            int,
        )
        assert (
            BrollyStatsRollupTask.get_min_seconds_interval_between_executions() == 72000
        )

    @pytest.mark.asyncio
    @patch("tasks.brolly_stats_rollup.get_config", return_value=False)
    async def test_run_cron_task_while_disabled(self, mocker, dbsession):
        task = BrollyStatsRollupTask()

        result = await BrollyStatsRollupTask().run_cron_task(dbsession)
        assert result == {
            "uploaded": False,
            "reason": "telemetry disabled in codecov.yml",
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_cron_task_http_ok(self, mocker, dbsession):
        users = [UserFactory.create(name=name) for name in ("foo", "bar", "baz")]
        for user in users:
            dbsession.add(user)

        repos = [
            RepositoryFactory.create(
                name=name,
            )
            for name in ("abc", "def", "ghi", "jkl")
        ]
        for repo in repos:
            dbsession.add(repo)

        commits = [
            CommitFactory.create(
                message="",
                commitid=commitid,
                repository=repos[0],
            )
            for commitid in ("deadbeef", "cafebabe", "eggdad")
        ]
        for commit in commits:
            dbsession.add(commit)

        uploads = [
            UploadFactory.create(created_at=created_at, report=None)
            for created_at in (
                _get_n_hours_ago(5),
                _get_n_hours_ago(16),
                _get_n_hours_ago(30),
            )
        ]
        for upload in uploads:
            dbsession.add(upload)

        install_id = ConstantsFactory.create(key="install_id", value=str(uuid.uuid4()))
        version = ConstantsFactory.create(key="version", value="hello")
        dbsession.add(install_id)
        dbsession.add(version)

        install_id_val = dbsession.query(Constants).get("install_id").value
        version_val = dbsession.query(Constants).get("version").value
        print("mattmatt", install_id_val, version_val)

        dbsession.flush()

        mock_request = respx.post(DEFAULT_BROLLY_ENDPOINT).mock(
            return_value=httpx.Response(200)
        )

        task = BrollyStatsRollupTask()
        result = await task.run_cron_task(dbsession)

        assert mock_request.called
        assert result == {
            "uploaded": True,
            "payload": {
                "install_id": install_id.value,
                "users": 3,
                "repos": 4,
                "commits": 3,
                "uploads_24h": 2,
                "anonymous": True,
                "version": version.value,
            },
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_cron_task_not_ok(self, mocker, dbsession):
        mock_request = respx.post(DEFAULT_BROLLY_ENDPOINT).mock(
            return_value=httpx.Response(500)
        )

        install_id = ConstantsFactory.create(key="install_id", value=str(uuid.uuid4()))
        version = ConstantsFactory.create(key="version", value="hello")
        dbsession.add(install_id)
        dbsession.add(version)

        dbsession.flush()

        task = BrollyStatsRollupTask()
        result = await task.run_cron_task(dbsession)
        assert mock_request.called
        assert result == {
            "uploaded": False,
            "payload": {
                "install_id": install_id.value,
                "users": 0,
                "repos": 0,
                "commits": 0,
                "uploads_24h": 0,
                "anonymous": True,
                "version": version.value,
            },
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_cron_task_include_admin_email_if_populated(
        self, mocker, dbsession
    ):
        mock_request = respx.post(DEFAULT_BROLLY_ENDPOINT).mock(
            return_value=httpx.Response(200)
        )

        mocker.patch.object(
            BrollyStatsRollupTask, "_get_admin_email", return_value="hello"
        )

        install_id = ConstantsFactory.create(key="install_id", value=str(uuid.uuid4()))
        version = ConstantsFactory.create(key="version", value="hello")
        dbsession.add(install_id)
        dbsession.add(version)

        dbsession.flush()

        task = BrollyStatsRollupTask()
        result = await task.run_cron_task(dbsession)
        assert mock_request.called
        assert result == {
            "uploaded": True,
            "payload": {
                "install_id": install_id.value,
                "users": 0,
                "repos": 0,
                "commits": 0,
                "uploads_24h": 0,
                "anonymous": True,
                "version": version.value,
                "admin_email": "hello",
            },
        }
