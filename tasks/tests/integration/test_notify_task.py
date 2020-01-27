import pytest
from decimal import Decimal
from tasks.notify import NotifyTask
from database.models import Pull
from database.tests.factories import CommitFactory, RepositoryFactory
from services.notification.notifiers.base import NotificationResult
from services.archive import ArchiveService


@pytest.mark.integration
class TestNotifyTask(object):

    @pytest.mark.asyncio
    async def test_simple_call_no_notifiers(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        mocked_app = mocker.patch.object(NotifyTask, 'app')
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token='test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy',
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

    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://codecov.io'
        mocked_app = mocker.patch.object(NotifyTask, 'app')
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token='test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy',
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
        with open('tasks/tests/samples/sample_chunks_1.txt') as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f'v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt'
            mock_storage.write_file('archive', chunks_url, content)
            master_chunks_url = f'v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt'
            mock_storage.write_file('archive', master_chunks_url, content)
        result = await task.run_async(
            dbsession, commit.repoid, commit.commitid, current_yaml={'coverage': {'status': {'project': True}}}
        )
        expected_result = {
            'notified': True,
            'notifications': [
                {
                    'notifier': 'status-project',
                    'title': 'default',
                    'result': dict(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation='already_done',
                        data_sent={
                            'title': 'codecov/project',
                            'state': 'success',
                            'message': '85.00% (+0.00%) compared to 17a71a9'
                        },
                        data_received=None
                    )
                }
            ]
        }
        assert result['notifications'] == expected_result['notifications']
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers_no_pull_request(self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'https://myexamplewebsite.io'
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token='test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy',
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
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f'v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt'
            mock_storage.write_file('archive', chunks_url, content)
            master_chunks_url = f'v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt'
            mock_storage.write_file('archive', master_chunks_url, content)
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
                    'result': dict(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'title': 'codecov/project',
                            'state': 'success',
                            'message': '85.00% (+0.00%) compared to 598a170'
                        },
                        data_received={'id': 8459148187}
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-patch',
                    'result': dict(
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
                    'result': dict(
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
            owner__unencrypted_oauth_token='test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy',
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
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f'v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt'
            mock_storage.write_file('archive', chunks_url, content)
            master_chunks_url = f'v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt'
            mock_storage.write_file('archive', master_chunks_url, content)
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
                    'result': dict(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'title': 'codecov/project',
                            'state': 'success',
                            'message': '85.00% (+0.00%) compared to 30cc1ed'},
                        data_received={'id': 8459159593}
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-patch',
                    'result': dict(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'title': 'codecov/patch',
                            'state': 'success',
                            'message': 'Coverage not affected when comparing 30cc1ed...2e2600a'},
                        data_received={'id': 8459159678}
                    ),
                    'title': 'default'
                },
                {
                    'notifier': 'status-changes',
                    'result': dict(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            'title': 'codecov/changes',
                            'state': 'success',
                            'message': 'No unexpected coverage changes found'},
                        data_received={'id': 8459159753}
                    ),
                    'title': 'default'
                }]
        }
        import pprint
        pprint.pprint(result)
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_simple_call_status_and_notifiers(
        self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"][
            "codecov_url"
        ] = "https://myexamplewebsite.io"
        mocker.patch.object(NotifyTask, "app")
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token="test5o0qa150h9b1skiamm7oktq9kkz7nr6issgh",
            owner__username="ThiagoCodecov",
            name="example-python",
            image_token="abcdefghij",
        )
        dbsession.add(repository)
        dbsession.flush()
        master_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="6dc3afd80a8deea5ea949d284d996d58811cd01d",
            repository=repository,
            author=repository.owner,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="thiago/f/something",
            commitid="7a7153d24f76c9ad58f421bcac8276203d589b1a",
            parent_commit_id=master_commit.commitid,
            repository=repository,
            author=repository.owner,
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
            master_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt"
            )
            mock_storage.write_file("archive", master_chunks_url, content)
        result = await task.run_async(
            dbsession,
            commit.repoid,
            commit.commitid,
            current_yaml={
                "comment": {
                    "layout": "reach, diff, flags, files, footer",
                    "behavior": "default",
                    "require_changes": False,
                    "require_base": False,
                    "require_head": True,
                },
                "coverage": {
                    "status": {"project": True, "patch": True, "changes": True},
                    "notify": {
                        "webhook": {
                            "default": {"url": "https://enntvaucxboe.x.pipedream.net"}
                        },
                        "slack": {
                            "default": {
                                "url": "https://hooks.slack.com/services/testkylhk/test01hg7/testohfnij1e83uy4xt8sxml"
                            }
                        },
                    },
                },
            },
        )
        expected_author_dict = {
            "username": "ThiagoCodecov",
            "service_id": repository.owner.service_id,
            "email": repository.owner.email,
            "service": "github",
            "name": repository.owner.name,
        }
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "WebhookNotifier",
                    "result": dict(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            "repo": {
                                "url": "https://myexamplewebsite.io/gh/ThiagoCodecov/example-python",
                                "service_id": repository.service_id,
                                "name": "example-python",
                                "private": True,
                            },
                            "head": {
                                "author": expected_author_dict,
                                "url": "https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/7a7153d24f76c9ad58f421bcac8276203d589b1a",
                                "timestamp": "2019-02-01T17:59:47",
                                "totals": dict(
                                    [
                                        ("files", 3),
                                        ("lines", 20),
                                        ("hits", 17),
                                        ("misses", 3),
                                        ("partials", 0),
                                        ("coverage", "85.00000"),
                                        ("branches", 0),
                                        ("methods", 0),
                                        ("messages", 0),
                                        ("sessions", 1),
                                        ("complexity", 0),
                                        ("complexity_total", 0),
                                        (
                                            "diff",
                                            [
                                                1,
                                                2,
                                                1,
                                                1,
                                                0,
                                                "50.00000",
                                                0,
                                                0,
                                                0,
                                                0,
                                                0,
                                                0,
                                                0,
                                            ],
                                        ),
                                    ]
                                ),
                                "commitid": "7a7153d24f76c9ad58f421bcac8276203d589b1a",
                                "service_url": "https://github.com/ThiagoCodecov/example-python/commit/7a7153d24f76c9ad58f421bcac8276203d589b1a",
                                "branch": "thiago/f/something",
                                "message": "",
                            },
                            "base": {
                                "author": expected_author_dict,
                                "url": "https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/6dc3afd80a8deea5ea949d284d996d58811cd01d",
                                "timestamp": "2019-02-01T17:59:47",
                                "totals": {
                                    "files": 3,
                                    "lines": 20,
                                    "hits": 17,
                                    "misses": 3,
                                    "partials": 0,
                                    "coverage": "85.00000",
                                    "branches": 0,
                                    "methods": 0,
                                    "messages": 0,
                                    "sessions": 1,
                                    "complexity": 0,
                                    "complexity_total": 0,
                                    "diff": [
                                        1,
                                        2,
                                        1,
                                        1,
                                        0,
                                        "50.00000",
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                    ],
                                },
                                "commitid": "6dc3afd80a8deea5ea949d284d996d58811cd01d",
                                "service_url": "https://github.com/ThiagoCodecov/example-python/commit/6dc3afd80a8deea5ea949d284d996d58811cd01d",
                                "branch": "master",
                                "message": "",
                            },
                            "compare": {
                                "url": "https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/compare/6dc3afd80a8deea5ea949d284d996d58811cd01d...7a7153d24f76c9ad58f421bcac8276203d589b1a",
                                "message": "no change",
                                "coverage": Decimal("0.00"),
                                "notation": "",
                            },
                            "owner": {
                                "username": "ThiagoCodecov",
                                "service_id": repository.owner.service_id,
                                "service": "github",
                            },
                            "pull": {
                                "base": {
                                    "branch": "master",
                                    "commit": "6dc3afd80a8deea5ea949d284d996d58811cd01d",
                                },
                                "head": {
                                    "branch": "master",
                                    "commit": "7a7153d24f76c9ad58f421bcac8276203d589b1a",
                                },
                                "id": 17,
                                "merged": False,
                                "number": "17",
                                "open": True,
                            },
                        },
                        data_received=None,
                    ),
                    "title": "default",
                },
                {
                    "notifier": "SlackNotifier",
                    "result": dict(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            "text": "Coverage for <https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/7a7153d24f76c9ad58f421bcac8276203d589b1a|ThiagoCodecov/example-python> *no change* `<https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/compare/6dc3afd80a8deea5ea949d284d996d58811cd01d...7a7153d24f76c9ad58f421bcac8276203d589b1a|0.00%>` on `thiago/f/something` is `85.00000%` via `<https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/7a7153d24f76c9ad58f421bcac8276203d589b1a|7a7153d>`",
                            "author_name": "Codecov",
                            "author_link": "https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/7a7153d24f76c9ad58f421bcac8276203d589b1a",
                            "attachments": [],
                        },
                        data_received=None,
                    ),
                    "title": "default",
                },
                {
                    "notifier": "status-project",
                    "result": dict(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation="already_done",
                        data_sent={
                            "title": "codecov/project",
                            "state": "success",
                            "message": "85.00% (+0.00%) compared to 6dc3afd",
                        },
                        data_received=None,
                    ),
                    "title": "default",
                },
                {
                    "notifier": "status-patch",
                    "result": dict(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation="already_done",
                        data_sent={
                            "title": "codecov/patch",
                            "state": "success",
                            "message": "Coverage not affected when comparing 6dc3afd...7a7153d",
                        },
                        data_received=None,
                    ),
                    "title": "default",
                },
                {
                    "notifier": "status-changes",
                    "result": dict(
                        notification_attempted=False,
                        notification_successful=None,
                        explanation="already_done",
                        data_sent={
                            "title": "codecov/changes",
                            "state": "success",
                            "message": "No unexpected coverage changes found",
                        },
                        data_received=None,
                    ),
                    "title": "default",
                },
                {
                    "notifier": "comment",
                    "result": dict(
                        notification_attempted=True,
                        notification_successful=True,
                        explanation=None,
                        data_sent={
                            "commentid": None,
                            "pullid": 17,
                            "message": [
                                "# "
                                "[Codecov](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/pull/17?src=pr&el=h1) "
                                "Report",
                                "> Merging "
                                "[#17](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/pull/17?src=pr&el=desc) "
                                "into "
                                "[master](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/6dc3afd80a8deea5ea949d284d996d58811cd01d&el=desc) "
                                "will **not change** coverage by `%`.",
                                "> The diff coverage is `n/a`.",
                                "",
                                "[![Impacted file tree "
                                "graph](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/pull/17/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/pull/17?src=pr&el=tree)",
                                "",
                                "```diff",
                                "@@           Coverage Diff           @@",
                                "##           master      #17   +/-   ##",
                                "=======================================",
                                "  Coverage   85.00%   85.00%           ",
                                "=======================================",
                                "  Files           3        3           ",
                                "  Lines          20       20           ",
                                "=======================================",
                                "  Hits           17       17           ",
                                "  Misses          3        3           ",
                                "```",
                                "",
                                "| Flag | Coverage Δ | |",
                                "|---|---|---|",
                                "| #unit | `85.00% <ø> (ø)` | :arrow_up: |",
                                "",
                                "",
                                "------",
                                "",
                                "[Continue to review full report at "
                                "Codecov](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/pull/17?src=pr&el=continue).",
                                "> **Legend** - [Click here to learn "
                                "more](https://docs.codecov.io/docs/codecov-delta)",
                                "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = "
                                "missing data`",
                                "> Powered by "
                                "[Codecov](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/pull/17?src=pr&el=footer). "
                                "Last update "
                                "[6dc3afd...7a7153d](https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/pull/17?src=pr&el=lastupdated). "
                                "Read the [comment "
                                "docs](https://docs.codecov.io/docs/pull-request-comments).",
                                "",
                            ],
                        },
                        data_received={"id": 572315846},
                    ),
                    "title": "comment",
                },
            ],
        }
        import pprint
        pull = dbsession.query(Pull).filter_by(pullid=17, repoid=commit.repoid).first()
        assert pull.commentid == '572315846'

        pprint.pprint(result)
        assert len(result["notifications"]) == len(expected_result["notifications"])
        for expected, actual in zip(
            sorted(result["notifications"], key=lambda x: x["notifier"]),
            sorted(expected_result["notifications"], key=lambda x: x["notifier"]),
        ):
            assert expected == actual
        assert sorted(result["notifications"], key=lambda x: x["notifier"]) == sorted(
            expected_result["notifications"], key=lambda x: x["notifier"]
        )
        assert result == expected_result
