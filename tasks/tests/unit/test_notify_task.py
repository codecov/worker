import pytest
from asyncio import Future
from celery.exceptions import Retry
from tasks.notify import default_if_true, NotifyTask
from database.tests.factories import RepositoryFactory, CommitFactory, OwnerFactory


class TestNotifyTaskHelpers(object):

    def test_default_if_true(self):
        assert list(default_if_true(True)) == [('default', {})]
        assert list(default_if_true(None)) == []
        assert list(default_if_true(False)) == []
        assert list(default_if_true({'custom': {'enabled': False}})) == []
        assert list(default_if_true({'custom': False})) == []
        assert list(default_if_true({'custom': True})) == [('custom', {})]
        assert list(default_if_true({'custom': {'enabled': True}})) == [('custom', {'enabled': True})]

    def test_get_notifiers_instances_only_third_party(self, dbsession, mock_configuration):
        mock_configuration.params['services'] = {'notifications': {'slack': ['slack.com']}}
        task = NotifyTask()
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            owner__username='ThiagoCodecov',
            yaml={'codecov': {'max_report_age': '1y ago'}},
            name='example-python'
        )
        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {
            'coverage': {
                'notify': {
                    'slack': {
                        'default': {
                            'field': '1y ago'
                        }
                    }
                }
            }
        }
        instances = list(task.get_notifiers_instances(repository, current_yaml))
        assert len(instances) == 1
        instance = instances[0]
        assert instance.repository == repository
        assert instance.title == 'default'
        assert instance.notifier_yaml_settings == {'field': '1y ago'}
        assert instance.site_settings == ['slack.com']
        assert instance.current_yaml == current_yaml

    def test_fetch_parent(self, dbsession):
        task = NotifyTask()
        owner = OwnerFactory.create(
            unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            username='ThiagoCodecov',
        )
        repository = RepositoryFactory.create(
            owner=owner,
            yaml={'codecov': {'max_report_age': '1y ago'}},
        )
        different_repository = RepositoryFactory.create(
            owner=owner,
            yaml={'codecov': {'max_report_age': '1y ago'}},
        )
        dbsession.add(repository)
        right_parent_commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='master',
            commitid='17a71a9a2f5335ed4d00496c7bbc6405f547a527',
            repository=repository
        )
        wrong_parent_commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='master',
            commitid='17a71a9a2f5335ed4d00496c7bbc6405f547a527',
            repository=different_repository
        )
        another_wrong_parent_commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='master',
            commitid='bf303450570d7a84f8c3cdedac5ac23e27a64c19',
            repository=repository
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='649eaaf2924e92dc7fd8d370ddb857033231e67a',
            parent_commit_id='17a71a9a2f5335ed4d00496c7bbc6405f547a527',
            repository=repository
        )
        dbsession.add(commit)
        dbsession.add(another_wrong_parent_commit)
        dbsession.add(repository)
        dbsession.add(different_repository)
        dbsession.add(right_parent_commit)
        dbsession.add(wrong_parent_commit)
        dbsession.flush()
        assert task.fetch_parent(commit) == right_parent_commit


class TestNotifyTask(object):

    @pytest.mark.asyncio
    async def test_simple_call_no_notifications(self, dbsession, mocker, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        mocker.patch.object(NotifyTask, 'app')
        mocked_should_send_notifications = mocker.patch.object(
            NotifyTask, 'should_send_notifications', return_value=False
        )
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask, 'fetch_and_update_whether_ci_passed',
            return_value=fetch_and_update_whether_ci_passed_result
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='649eaaf2924e92dc7fd8d370ddb857033231e67a',
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        result = await task.run_async(
            dbsession, commit.repoid, commit.commitid, current_yaml={}
        )
        assert result == {'notified': False, 'notifications': None}
        mocked_should_send_notifications.assert_called_with(
            {}, commit, fetch_and_update_whether_ci_passed_result.result()
        )

    @pytest.mark.asyncio
    async def test_simple_call_should_delay(self, dbsession, mocker, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        mocker.patch.object(NotifyTask, 'app')
        mocked_should_wait_longer = mocker.patch.object(
            NotifyTask, 'should_wait_longer', return_value=True
        )
        mocked_retry = mocker.patch.object(NotifyTask, 'retry', side_effect=Retry())
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask, 'fetch_and_update_whether_ci_passed',
            return_value=fetch_and_update_whether_ci_passed_result
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='649eaaf2924e92dc7fd8d370ddb857033231e67a',
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        with pytest.raises(Retry):
            await task.run_async(
                dbsession, commit.repoid, commit.commitid, current_yaml={}
            )
        mocked_retry.assert_called_with(countdown=15, max_retries=10)
        mocked_should_wait_longer.assert_called_with(
            {}, commit, fetch_and_update_whether_ci_passed_result.result()
        )

    @pytest.mark.asyncio
    async def test_simple_call_should_delay_using_integration(self, dbsession, mocker, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        mocker.patch.object(NotifyTask, 'app')
        mocked_should_wait_longer = mocker.patch.object(
            NotifyTask, 'should_wait_longer', return_value=True
        )
        mocked_retry = mocker.patch.object(NotifyTask, 'retry', side_effect=Retry())
        fetch_and_update_whether_ci_passed_result = Future()
        fetch_and_update_whether_ci_passed_result.set_result({})
        mocker.patch.object(
            NotifyTask, 'fetch_and_update_whether_ci_passed',
            return_value=fetch_and_update_whether_ci_passed_result
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='649eaaf2924e92dc7fd8d370ddb857033231e67a',
            repository__using_integration=True
        )
        dbsession.add(commit)
        dbsession.flush()
        task = NotifyTask()
        with pytest.raises(Retry):
            await task.run_async(
                dbsession, commit.repoid, commit.commitid, current_yaml={}
            )
        mocked_retry.assert_called_with(countdown=180, max_retries=5)
        mocked_should_wait_longer.assert_called_with(
            {}, commit, fetch_and_update_whether_ci_passed_result.result()
        )
