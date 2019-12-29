import pytest

from tasks.notify import NotifyTask
from database.tests.factories import CommitFactory, RepositoryFactory
from services.notification.notifiers.base import NotificationResult


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
        expected_result = {
            'notified': True,
            'notifications': []
        }
        assert result == expected_result
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
        expected_result = {
            'notified': True,
            'notifications': [
                {
                    'notifier': 'status-project',
                    'title': 'default',
                    'result': NotificationResult(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation='already_done',
                        data_sent={
                            'title': 'codecov/project',
                            'state': 'success',
                            'message': '85.00000% (+0.00%) compared to 17a71a9'
                        },
                        data_received=None
                    )
                }
            ]
        }
        assert result['notifications'] == expected_result['notifications']
        assert result == expected_result
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
        mock_configuration.params['setup']['codecov_url'] = 'https://myexamplewebsite.io'
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
            commitid='598a170616a6c61898bb673e7b314c5dadb81d1e',
            repository=repository
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='cd2336eec5d0108ce964b6cfba876863498c44a5',
            parent_commit_id=master_commit.commitid,
            repository=repository
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open('tasks/tests/samples/sample_chunks_1.txt') as f:
            mock_storage.read_file.return_value = f.read().encode()
        result = await task.run_async(
            dbsession, commit.repoid, commit.commitid,
            current_yaml={
                'coverage': {
                    'status': {
                        'project': True,
                        'patch': True,
                        'changes': True
                    }
                }
            }
        )
        expected_result = {
            'notified': True,
            'notifications': [
                {
                    'notifier': 'status-project',
                    'result': NotificationResult(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'title': 'codecov/project',
                            'state': 'success',
                            'message': '85.00000% (+0.00%) compared to 598a170'
                        },
                        data_received={'id': 8459148187}
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-patch',
                    'result': NotificationResult(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'title': 'codecov/patch',
                            'state': 'success',
                            'message': 'Coverage not affected when comparing 598a170...cd2336e'
                        },
                        data_received={'id': 8459148237}
                    ),
                    'title': 'default'},
                {
                    'notifier': 'status-changes',
                    'result': NotificationResult(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'title': 'codecov/changes',
                            'state': 'success',
                            'message': 'No unexpected coverage changes found'
                        },
                        data_received={'id': 8459148290}
                    ),
                    'title': 'default'
                }
            ]
        }
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers_with_pull_request(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://myexamplewebsite.io'
        mocked_app = mocker.patch.object(NotifyTask, 'app')
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
            commitid='30cc1ed751a59fa9e7ad8e79fff41a6fe11ef5dd',
            repository=repository
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='2e2600aa09525e2e1e1d98b09de61454d29c94bb',
            parent_commit_id=master_commit.commitid,
            repository=repository
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open('tasks/tests/samples/sample_chunks_1.txt') as f:
            mock_storage.read_file.return_value = f.read().encode()
        result = await task.run_async(
            dbsession, commit.repoid, commit.commitid,
            current_yaml={
                'coverage': {
                    'status': {
                        'project': True,
                        'patch': True,
                        'changes': True
                    }
                }
            }
        )
        expected_result = {
            'notified': True,
            'notifications': [
                {
                    'notifier': 'status-project',
                    'result': NotificationResult(
                        notification_attempted=True, notification_successful=True, explanation=None, data_sent={'title': 'codecov/project', 'state': 'success', 'message': '85.00000% (+0.00%) compared to 30cc1ed'}, data_received={'id': 8459159593}
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-patch',
                    'result': NotificationResult(
                        notification_attempted=True, notification_successful=True, explanation=None, data_sent={'title': 'codecov/patch', 'state': 'success', 'message': 'Coverage not affected when comparing 30cc1ed...2e2600a'}, data_received={'id': 8459159678}
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-changes',
                    'result': NotificationResult(
                        notification_attempted=True, notification_successful=True, explanation=None, data_sent={'title': 'codecov/changes', 'state': 'success', 'message': 'No unexpected coverage changes found'}, data_received={'id': 8459159753}
                    ),
                    'title': 'default'
                }]
        }
        import pprint
        pprint.pprint(result)
        assert result == expected_result
        mocked_app.send_task.assert_called_with(
            'app.tasks.pulls.Sync',
            args=None, kwargs=dict(force=True, repoid=commit.repoid, pullid=15)
        )
