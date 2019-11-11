import json
import asyncio
from pathlib import Path
from asyncio import Future

import pytest
from torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError

from tasks.status_set_pending import StatusSetPendingTask

here = Path(__file__)


class TestSetPendingTaskUnit(object):

    @pytest.mark.asyncio
    async def test_no_status(self, mocker, mock_configuration, dbsession):
        mocked_1 = mocker.patch('tasks.status_set_pending.get_repo')
        f = asyncio.Future()
        repo = mocker.MagicMock(
            service='github',
            data=dict(yaml={'coverage': {'status': None}}),
            set_commit_status=mocker.MagicMock(return_value=None)
        )
        f.set_result(repo)
        mocked_1.return_value = f

        repoid = '1'
        commitid = 'x'
        branch = 'master'
        on_a_pull_request = False
        res = await StatusSetPendingTask().run_async(dbsession, repoid, commitid, branch, on_a_pull_request)
        assert res is None
        assert not repo.set_commit_status.called

    # def test_skip_set_pending(self):
    #     repo = Mock(service='github', slug='owner/repo',
    #                 log=Mock(),
    #                 data=dict(yaml={'coverage': {'status': {'project': {'custom': {'target': 80, 'set_pending': False}}}}}),
    #                 get_commit_statuses=Mock(return_value=self.future(Status([]))),
    #                 set_commit_status=Mock(return_value=self.future(None)))
    #     status.set_pending(repository=repo, repoid=1, commitid='a', branch='master', on_a_pull_request=False)
    #     assert not repo.set_commit_status.called

    # def test_skip_set_pending_unknown_branch(self):
    #     repo = Mock(service='github', slug='owner/repo',
    #                 log=Mock(),
    #                 data=dict(yaml={'coverage': {'status': {'project': {'custom': {'target': 80, 'branches': ['master']}}}}}),
    #                 get_commit_statuses=Mock(return_value=self.future(Status([]))),
    #                 set_commit_status=Mock(return_value=self.future(None)))
    #     status.set_pending(repository=repo, repoid=1, commitid='a', on_a_pull_request=False)
    #     assert not repo.set_commit_status.called

    # @_data(('patch', True), ('project', True), ('changes', True),
    #        ('patch', False), ('project', False), ('changes', False))
    # def test_set_error(self, (context, cc_status_exists)):
    #     statuses = ([{'url': None, 'state': 'pending', 'context': 'ci', 'time': '2015-12-21T16:54:13Z'}] +
    #                 ([{'url': None, 'state': 'pending', 'context': 'codecov/'+context, 'time': '2015-12-21T16:54:13Z'}] if cc_status_exists else []))
    #     repo = Mock(service='github', slug='owner/repo',
    #                 log=Mock(),
    #                 token={'username': 'bot'},
    #                 data=dict(yaml={'coverage': {'status': {context: {'default': {'target': 80}}}}}),
    #                 get_commit_statuses=Mock(return_value=self.future(Status(statuses))),
    #                 set_commit_status=Mock(return_value=self.future(None)))

    #     status.set_error(repository=repo, repoid=1, commitid='a')
    #     if cc_status_exists:
    #         repo.set_commit_status.assert_called_with(commit='a',
    #                                                   status='error',
    #                                                   context='codecov/'+context,
    #                                                   description='Coverage not measured fully because CI failed',
    #                                                   url=self.get_url('gh/owner/repo/commit/a'))
    #     else:
    #         assert not repo.set_commit_status.called

    # @_data(('patch', 'master', False),
    #        ('patch', 'master', False),
    #        ('patch', 'master', True),
    #        ('patch', 'skip', False),
    #        ('project', 'master', False),
    #        ('project', 'skip', False),
    #        ('project', 'master', True),
    #        ('changes', 'master', False),
    #        ('changes', 'master', False),
    #        ('changes', 'master', True),
    #        ('changes', 'skip', False))
    # def test_set_pending(self, (context, branch, cc_status_exists)):
    #     statuses = ([{'url': None, 'state': 'pending', 'context': 'ci', 'time': '2015-12-21T16:54:13Z'}] +
    #                 ([{'url': None, 'state': 'pending', 'context': 'codecov/'+context+'/custom', 'time': '2015-12-21T16:54:13Z'}] if cc_status_exists else []))
    #     repo = Mock(service='github', slug='owner/repo',
    #                 log=Mock(),
    #                 data=dict(yaml={'coverage': {'status': {context: {'custom': {'target': 80, 'branches': ['!skip']}}}}}),
    #                 get_commit_statuses=Mock(return_value=self.future(Status(statuses))),
    #                 set_commit_status=Mock(return_value=self.future(None)))
    #     status.set_pending(repository=repo, repoid=1, commitid='a', branch=branch, on_a_pull_request=False)
    #     if branch == 'master' and not cc_status_exists:
    #         self.skipTest("[TODO] need to respect 'only_pulls=true' and 'base=pr'")
    #         assert repo.set_commit_status.assert_called_with(commit='a',
    #                                                          status='pending',
    #                                                          context='codecov/'+context+'/custom',
    #                                                          description='Collecting and processing reports...',
    #                                                          url=self.get_url('gh/owner/repo/commit/a'))
    #     else:
    #         assert not repo.set_commit_status.called