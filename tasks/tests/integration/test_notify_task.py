import pytest
from decimal import Decimal
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

    @pytest.mark.asyncio
    async def test_simple_call_status_and_notifiers(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
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
            repository=repository,
            author=repository.owner
        )
        commit = CommitFactory.create(
            message='',
            pullid=None,
            branch='test-branch-1',
            commitid='05732bbb3b85e06dd88539761e9fc9d8113b4be8',
            parent_commit_id=master_commit.commitid,
            repository=repository,
            author=repository.owner
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
                    },
                    'notify': {
                        'webhook': {
                            'default': {
                                'url': 'https://enps01r1xxn.x.pipedream.net'
                            }
                        },
                        'slack': {
                            'default': {
                                'url': 'https://hooks.slack.com/services/testkylhk/test01hg7/testohfnij1e83uy4xt8sxml'
                            }
                        }
                    }
                }
            }
        )
        expected_author_dict = {
            'username': 'ThiagoCodecov',
            'service_id': repository.owner.service_id, 'email': None, 'service': 'github',
            'name': repository.owner.name
        }
        expected_result = {
            'notified': True,
            'notifications': [
                {
                    'notifier': 'WebhookNotifier',
                    'result': NotificationResult(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'repo': {
                                'url': 'https://myexamplewebsite.io/gh/ThiagoCodecov/example-python',
                                'service_id': repository.service_id, 'name': 'example-python', 'private': True
                            },
                            'head': {
                                'author': expected_author_dict,
                                'url': 'https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/05732bbb3b85e06dd88539761e9fc9d8113b4be8', 'timestamp': '2019-02-01T17:59:47',
                                'totals': dict([('files', 3), ('lines', 20), ('hits', 17), ('misses', 3), ('partials', 0), ('coverage', '85.00000'), ('branches', 0), ('methods', 0), ('messages', 0), ('sessions', 1), ('complexity', 0), ('complexity_total', 0), ('diff', [1, 2, 1, 1, 0, '50.00000', 0, 0, 0, 0, 0, 0, 0])]),
                                'commitid': '05732bbb3b85e06dd88539761e9fc9d8113b4be8',
                                'service_url': 'https://github.com/ThiagoCodecov/example-python/commit/05732bbb3b85e06dd88539761e9fc9d8113b4be8', 'branch': 'test-branch-1', 'message': ''
                            },
                            'base': {
                                'author': expected_author_dict,
                                'url': 'https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/30cc1ed751a59fa9e7ad8e79fff41a6fe11ef5dd', 'timestamp': '2019-02-01T17:59:47',
                                'totals': dict([('files', 3), ('lines', 20), ('hits', 17), ('misses', 3), ('partials', 0), ('coverage', '85.00000'), ('branches', 0), ('methods', 0), ('messages', 0), ('sessions', 1), ('complexity', 0), ('complexity_total', 0), ('diff', [1, 2, 1, 1, 0, '50.00000', 0, 0, 0, 0, 0, 0, 0])]),
                                'commitid': '30cc1ed751a59fa9e7ad8e79fff41a6fe11ef5dd',
                                'service_url': 'https://github.com/ThiagoCodecov/example-python/commit/30cc1ed751a59fa9e7ad8e79fff41a6fe11ef5dd', 'branch': 'master', 'message': ''
                            },
                            'compare': {
                                'url': 'https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/compare/30cc1ed751a59fa9e7ad8e79fff41a6fe11ef5dd...05732bbb3b85e06dd88539761e9fc9d8113b4be8', 'message': 'no change', 'coverage': Decimal('0.00'), 'notation': ''
                            },
                            'owner': {
                                'username': 'ThiagoCodecov',
                                'service_id': repository.owner.service_id,
                                'service': 'github'
                            },
                            'pull': None
                        },
                        data_received=None
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'SlackNotifier',
                    'result': NotificationResult(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'text': 'Coverage for <https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/05732bbb3b85e06dd88539761e9fc9d8113b4be8|ThiagoCodecov/example-python> *no change* `<https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/compare/30cc1ed751a59fa9e7ad8e79fff41a6fe11ef5dd...05732bbb3b85e06dd88539761e9fc9d8113b4be8|0.00%>` on `test-branch-1` is `85.00000%` via `<https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/05732bbb3b85e06dd88539761e9fc9d8113b4be8|05732bb>`', 'author_name': 'Codecov', 'author_link': 'https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/05732bbb3b85e06dd88539761e9fc9d8113b4be8', 'attachments': []
                        },
                        data_received=None
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-project',
                    'result': NotificationResult(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation='already_done',
                        data_sent={
                            'title': 'codecov/project', 'state': 'success', 'message': '85.00000% (+0.00%) compared to 30cc1ed'
                        },
                        data_received=None
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-patch',
                    'result': NotificationResult(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation='already_done',
                        data_sent={
                            'title': 'codecov/patch', 'state': 'success', 'message': 'Coverage not affected when comparing 30cc1ed...05732bb'
                        },
                        data_received=None
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-changes',
                    'result': NotificationResult(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation='already_done',
                        data_sent={
                            'title': 'codecov/changes', 'state': 'success', 'message': 'No unexpected coverage changes found'
                        },
                        data_received=None
                    ),
                    'title': 'default'
                }
            ]
        }
        import pprint
        pprint.pprint(result)
        assert sorted(result['notifications'], key=lambda x: x['notifier']) == sorted(expected_result['notifications'], key=lambda x: x['notifier'])
        assert result == expected_result
