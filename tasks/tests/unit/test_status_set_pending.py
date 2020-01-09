import json
import asyncio
from pathlib import Path
from asyncio import Future

import pytest
from torngit.status import Status

from tasks.status_set_pending import StatusSetPendingTask

here = Path(__file__)


class TestSetPendingTaskUnit(object):

    @pytest.mark.asyncio
    async def test_no_status(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch('tasks.status_set_pending.get_repo_provider_service_by_id')
        repo = mocker.MagicMock(
            service='github',
            data=dict(repo=dict(repoid=123)),
            set_commit_status=mocker.MagicMock(return_value=None)
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch('tasks.status_set_pending.fetch_current_yaml_from_provider_via_reference')
        fetch_current_yaml = Future()
        fetch_current_yaml.set_result({'coverage': {'status': None}})
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        repoid = '1'
        commitid = 'x'
        branch = 'master'
        on_a_pull_request = False
        res = await StatusSetPendingTask().run_async(dbsession, repoid, commitid, branch, on_a_pull_request)
        assert res is None
        assert not repo.set_commit_status.called

    @pytest.mark.asyncio
    async def test_not_in_beta(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch('tasks.status_set_pending.get_repo_provider_service_by_id')
        repo = mocker.MagicMock(
            service='github',
            data=dict(repo=dict(repoid=123)),
            set_commit_status=mocker.MagicMock(return_value=None)
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch('tasks.status_set_pending.fetch_current_yaml_from_provider_via_reference')
        fetch_current_yaml = Future()
        fetch_current_yaml.set_result({'coverage': {'status': None}})
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [False]

        repoid = '1'
        commitid = 'x'
        branch = 'master'
        on_a_pull_request = False
        with pytest.raises(AssertionError, match='Pending disabled. Please request to be in beta.'):
            await StatusSetPendingTask().run_async(dbsession, repoid, commitid, branch, on_a_pull_request)
        mock_redis.sismember.assert_called_with('beta.pending', repoid)

    @pytest.mark.asyncio
    async def test_skip_set_pending(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch('tasks.status_set_pending.get_repo_provider_service_by_id')
        get_commit_statuses = Future()
        set_commit_status = Future()
        repo = mocker.MagicMock(
            service='github',
            slug='owner/repo',
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mocker.MagicMock(return_value=get_commit_statuses),
            set_commit_status=mocker.MagicMock(return_value=set_commit_status)
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch('tasks.status_set_pending.fetch_current_yaml_from_provider_via_reference')
        fetch_current_yaml = Future()
        fetch_current_yaml.set_result({'coverage': {'status': {'project': {'custom': {'target': 80, 'set_pending': False}}}}})
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        get_commit_statuses.set_result(Status([]))
        set_commit_status.set_result(None)

        repoid = 1
        commitid = 'a'
        branch = 'master'
        on_a_pull_request = False
        res = await StatusSetPendingTask().run_async(dbsession, repoid, commitid, branch, on_a_pull_request)
        assert not repo.set_commit_status.called
        assert res is None

    @pytest.mark.asyncio
    async def test_skip_set_pending_unknown_branch(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch('tasks.status_set_pending.get_repo_provider_service_by_id')
        get_commit_statuses = Future()
        set_commit_status = Future()
        repo = mocker.MagicMock(
            service='github',
            slug='owner/repo',
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mocker.MagicMock(return_value=get_commit_statuses),
            set_commit_status=mocker.MagicMock(return_value=set_commit_status)
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch('tasks.status_set_pending.fetch_current_yaml_from_provider_via_reference')
        fetch_current_yaml = Future()
        fetch_current_yaml.set_result({'coverage': {'status': {'project': {'custom': {'target': 80, 'branches': ['master']}}}}})
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        get_commit_statuses.set_result(Status([]))
        set_commit_status.set_result(None)

        repoid = 1
        commitid = 'a'
        branch = None
        on_a_pull_request = False
        res = await StatusSetPendingTask().run_async(dbsession, repoid, commitid, branch, on_a_pull_request)
        assert not repo.set_commit_status.called
        assert res is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize('context, branch, cc_status_exists', [
        ('patch', 'master', False),
        ('patch', 'master', False),
        ('patch', 'master', True),
        ('patch', 'skip', False),
        ('project', 'master', False),
        ('project', 'skip', False),
        ('project', 'master', True),
        ('changes', 'master', False),
        ('changes', 'master', False),
        ('changes', 'master', True),
        ('changes', 'skip', False)
    ])
    async def test_set_pending(self, context, branch, cc_status_exists, mocker, mock_configuration, dbsession, mock_redis):
        statuses = ([{'url': None, 'state': 'pending', 'context': 'ci', 'time': '2015-12-21T16:54:13Z'}] +
                    ([{'url': None, 'state': 'pending', 'context': 'codecov/'+context+'/custom', 'time': '2015-12-21T16:54:13Z'}] if cc_status_exists else []))

        mocked_1 = mocker.patch('tasks.status_set_pending.get_repo_provider_service_by_id')
        get_commit_statuses = Future()
        set_commit_status = Future()
        repo = mocker.MagicMock(
            service='github',
            slug='owner/repo',
            data=dict(repo=dict(repoid=123)),
            get_commit_statuses=mocker.MagicMock(return_value=get_commit_statuses),
            set_commit_status=mocker.MagicMock(return_value=set_commit_status)
        )
        mocked_1.return_value = repo

        mocked_2 = mocker.patch('tasks.status_set_pending.fetch_current_yaml_from_provider_via_reference')
        fetch_current_yaml = Future()
        fetch_current_yaml.set_result({'coverage': {'status': {context: {'custom': {'target': 80, 'branches': ['!skip']}}}}})
        mocked_2.return_value = fetch_current_yaml

        mock_redis.sismember.side_effect = [True]

        get_commit_statuses.set_result(Status(statuses))
        set_commit_status.set_result(None)

        repoid = 1
        commitid = 'a'
        on_a_pull_request = False
        await StatusSetPendingTask().run_async(dbsession, repoid, commitid, branch, on_a_pull_request)
        if branch == 'master' and not cc_status_exists:
            repo.set_commit_status.assert_called_with(commit='a',
                                                        status='pending',
                                                        context='codecov/'+context+'/custom',
                                                        description='Collecting reports and waiting for CI to complete',
                                                        url='https://codecov.io/gh/owner/repo/commit/a')
        else:
            assert not repo.set_commit_status.called
