import pytest

from tasks.notify import NotifyTask
from services.repository import get_repo_provider_service
from database.tests.factories import CommitFactory, RepositoryFactory


@pytest.mark.integration
class TestNotifyTask(object):

    @pytest.mark.asyncio
    async def test_simple_call_no_notifiers(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        mocked_app = mocker.patch.object(NotifyTask, 'app')
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            owner__username='ThiagoCodecov',
            yaml={'codecov': {'max_report_age': '1y ago'}},
            name='example-python'
        )
        dbsession.add(repository)
        dbsession.flush()
        master_commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='master',
            commitid='17a71a9a2f5335ed4d00496c7bbc6405f547a527',
            repository=repository
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='649eaaf2924e92dc7fd8d370ddb857033231e67a',
            repository=repository
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        result = await task.run_async(
            dbsession, commit.repoid, commit.commitid, current_yaml={}
        )
        assert result == {'notified': True}
        mocked_app.send_task.assert_called_with(
            'app.tasks.pulls.Sync',
            args=None,
            kwargs={
                'repoid': repository.repoid,
                'pullid': 11,
                'force': True
            }
        )

    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        mocked_app = mocker.patch.object(NotifyTask, 'app')
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            owner__username='ThiagoCodecov',
            name='example-python'
        )
        dbsession.add(repository)
        dbsession.flush()
        master_commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='master',
            commitid='17a71a9a2f5335ed4d00496c7bbc6405f547a527',
            repository=repository
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='649eaaf2924e92dc7fd8d370ddb857033231e67a',
            repository=repository
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        result = await task.run_async(
            dbsession, commit.repoid, commit.commitid, current_yaml={'coverage': {'status': {'project': True}}}
        )
        assert result == {'notified': True}
        mocked_app.send_task.assert_called_with(
            'app.tasks.pulls.Sync',
            args=None,
            kwargs={
                'repoid': repository.repoid,
                'pullid': 11,
                'force': True
            }
        )

    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers_no_pull_request(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token='testfwdxf9xgj2psfxcs6o1uar788t5ncva1rq88',
            owner__username='ThiagoCodecov',
            name='example-python'
        )
        dbsession.add(repository)
        dbsession.flush()
        master_commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='master',
            commitid='17a71a9a2f5335ed4d00496c7bbc6405f547a527',
            repository=repository
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='649eaaf2924e92dc7fd8d370ddb857033231e67a',
            parent_commit_id=master_commit.commitid,
            repository=repository
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        result = await task.run_async(
            dbsession, commit.repoid, commit.commitid, current_yaml={'coverage': {'status': {'project': True}}}
        )
        assert result == {'notified': True}
