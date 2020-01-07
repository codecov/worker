import json
from pathlib import Path
from asyncio import Future
from datetime import datetime

import pytest
from torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError

from tasks.upload import UploadTask
from tasks.upload_processor import upload_processor_task
from tasks.upload_finisher import upload_finisher_task
from database.tests.factories import CommitFactory, OwnerFactory, RepositoryFactory
from helpers.exceptions import RepositoryWithoutValidBotError
from services.archive import ArchiveService

here = Path(__file__)


@pytest.mark.integration
class TestUploadTaskIntegration(object):

    @pytest.mark.asyncio
    async def test_upload_task_call(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch('tasks.upload.chain')
        url = 'v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt'
        redis_queue = [
            {
                'url': url
            }
        ]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = jsonified_redis_queue

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},
            repository__name='example-python'
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {'was_setup': False, 'was_updated': True}
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'
        assert commit.parent_commit_id is None
        t1 = upload_processor_task.signature(
            args=({},),
            kwargs=dict(
                repoid=commit.repoid,
                commitid='abf6d4df662c47e32460020ab14abf9303581429',
                commit_yaml={'codecov': {'max_report_age': '1y ago'}},
                arguments_list=redis_queue
            )
        )
        t2 = upload_finisher_task.signature(
            kwargs=dict(
                repoid=commit.repoid,
                commitid='abf6d4df662c47e32460020ab14abf9303581429',
                commit_yaml={'codecov': {'max_report_age': '1y ago'}}
            )
        )
        mocked_1.assert_called_with(t1, t2)
        mock_redis.lpop.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=5, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_call_multiple_processors(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch('tasks.upload.chain')
        redis_queue = [
            {
                'part': 'part1'
            },
            {
                'part': 'part2'
            },
            {
                'part': 'part3'
            },
            {
                'part': 'part4'
            },
            {
                'part': 'part5'
            },
            {
                'part': 'part6'
            },
            {
                'part': 'part7'
            },
            {
                'part': 'part8'
            },
        ]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True] * 8 + [False]
        mock_redis.lpop.side_effect = jsonified_redis_queue

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},
            repository__name='example-python'
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {'was_setup': False, 'was_updated': True}
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'
        assert commit.parent_commit_id is None
        t1 = upload_processor_task.signature(
            args=({},),
            kwargs=dict(
                repoid=commit.repoid,
                commitid='abf6d4df662c47e32460020ab14abf9303581429',
                commit_yaml={'codecov': {'max_report_age': '1y ago'}},
                arguments_list=redis_queue[0:3]
            )
        )
        t2 = upload_processor_task.signature(
            args=(),
            kwargs=dict(
                repoid=commit.repoid,
                commitid='abf6d4df662c47e32460020ab14abf9303581429',
                commit_yaml={'codecov': {'max_report_age': '1y ago'}},
                arguments_list=redis_queue[3:6]
            )
        )
        t3 = upload_processor_task.signature(
            args=(),
            kwargs=dict(
                repoid=commit.repoid,
                commitid='abf6d4df662c47e32460020ab14abf9303581429',
                commit_yaml={'codecov': {'max_report_age': '1y ago'}},
                arguments_list=redis_queue[6:]
            )
        )
        t_final = upload_finisher_task.signature(
            kwargs=dict(
                repoid=commit.repoid,
                commitid='abf6d4df662c47e32460020ab14abf9303581429',
                commit_yaml={'codecov': {'max_report_age': '1y ago'}}
            )
        )
        mocked_1.assert_called_with(t1, t2, t3, t_final)
        mock_redis.lpop.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=5, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_proper_parent(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch('tasks.upload.chain')
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [False]

        owner = OwnerFactory.create(
            service='github',
            username='ThiagoCodecov',
            unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm'
        )
        dbsession.add(owner)

        repo = RepositoryFactory.create(
            owner=owner,
            yaml={'codecov': {'max_report_age': '1y ago'}},
            name='example-python'
        )
        dbsession.add(repo)

        parent_commit = CommitFactory.create(
            message='',
            commitid='c5b67303452bbff57cc1f49984339cde39eb1db5',
            repository=repo
        )

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository=repo
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {'was_setup': False, 'was_updated': True}
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'
        assert commit.parent_commit_id == 'c5b67303452bbff57cc1f49984339cde39eb1db5'
        assert not mocked_1.called
        assert not mock_redis.lpop.called
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=5, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_no_bot(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch.object(UploadTask, 'schedule_task')
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mocked_fetch_yaml = mocker.patch.object(UploadTask, 'fetch_commit_yaml_and_possibly_store')
        redis_queue = [
            {
                'part': 'part1'
            },
            {
                'part': 'part2'
            }
        ]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mock_redis.exists.side_effect = [True] * 2 + [False]
        mock_redis.lpop.side_effect = jsonified_redis_queue
        mock_get_repo_service = mocker.patch('tasks.upload.get_repo_provider_service')
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        commit = CommitFactory.create(
            message='',
            parent_commit_id=None,
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '764y ago'}},
            repository__name='example-python'
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {'was_setup': False, 'was_updated': False}
        assert expected_result == result
        assert commit.message == ''
        assert commit.parent_commit_id is None
        mocked_1.assert_called_with(
            commit, {'codecov': {'max_report_age': '764y ago'}}, redis_queue
        )
        assert not mocked_fetch_yaml.called
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=5, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_bot_no_permissions(self, mocker, mock_configuration, dbsession, mock_redis):
        mocked_1 = mocker.patch.object(UploadTask, 'schedule_task')
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mocked_fetch_yaml = mocker.patch.object(UploadTask, 'fetch_commit_yaml_and_possibly_store')
        redis_queue = [
            {
                'part': 'part1'
            },
            {
                'part': 'part2'
            }
        ]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mock_redis.exists.side_effect = [True] * 2 + [False]
        mock_redis.lpop.side_effect = jsonified_redis_queue
        mock_get_repo_service = mocker.patch('tasks.upload.get_repo_provider_service')
        mock_get_repo_service.side_effect = TorngitRepoNotFoundError('fake_response', 'message')
        commit = CommitFactory.create(
            message='',
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '764y ago'}},
            repository__name='example-python'
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {'was_setup': False, 'was_updated': False}
        assert expected_result == result
        assert commit.message == ''
        assert commit.parent_commit_id is None
        mocked_1.assert_called_with(
            commit, {'codecov': {'max_report_age': '764y ago'}}, redis_queue
        )
        assert not mocked_fetch_yaml.called
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=5, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_bot_unauthorized(self, mocker, mock_configuration, dbsession, mock_redis, mock_repo_provider):
        mocked_schedule_task = mocker.patch.object(UploadTask, 'schedule_task')
        mock_app = mocker.patch.object(UploadTask, 'app')
        mock_app.send_task.return_value = True
        redis_queue = [
            {
                'part': 'part1'
            },
            {
                'part': 'part2'
            }
        ]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mock_redis.exists.side_effect = [True] * 2 + [False]
        mock_redis.lpop.side_effect = jsonified_redis_queue
        f = Future()
        f.set_exception(TorngitClientError(401, 'response', 'message'))
        mock_repo_provider.get_commit.return_value = f
        mock_repo_provider.list_top_level_files.return_value = f
        commit = CommitFactory.create(
            message='',
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '764y ago'}}
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async_within_lock(
            dbsession, mock_redis, commit.repoid, commit.commitid
        )
        assert {'was_setup': False, 'was_updated': False} == result
        assert commit.message == ''
        assert commit.parent_commit_id is None
        mocked_schedule_task.assert_called_with(
            commit, {'codecov': {'max_report_age': '764y ago'}}, redis_queue
        )
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))


class TestUploadTaskUnit(object):

    def test_normalize_upload_arguments_no_changes(self, dbsession, mock_redis, mock_storage):
        mock_redis.get.return_value = b"Some weird value"
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        reportid = '5fbeee8b-5a41-4925-b59d-470b9d171235'
        arguments_with_redis_key = {
            'reportid': reportid,
            'random': 'argument'
        }
        result = UploadTask().normalize_upload_arguments(commit, arguments_with_redis_key, mock_redis)
        expected_result = {
            'reportid': '5fbeee8b-5a41-4925-b59d-470b9d171235',
            'random': 'argument'
        }
        assert expected_result == result

    def test_normalize_upload_arguments(self, dbsession, mock_redis, mock_storage, mocker):
        mocked_now = mocker.patch.object(ArchiveService, 'get_now')
        mocked_now.return_value = datetime(2019, 12, 3)
        mock_redis.get.return_value = b"Some weird value"
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repo_hash = ArchiveService.get_archive_hash(commit.repository)
        reportid = '5fbeee8b-5a41-4925-b59d-470b9d171235'
        arguments_with_redis_key = {
            'redis_key': 'commit_chunks.something',
            'reportid': reportid,
            'random': 'argument'
        }
        result = UploadTask().normalize_upload_arguments(commit, arguments_with_redis_key, mock_redis)
        expected_result = {
            'url': f'v4/raw/2019-12-03/{repo_hash}/{commit.commitid}/{reportid}.txt',
            'reportid': '5fbeee8b-5a41-4925-b59d-470b9d171235',
            'random': 'argument'
        }
        assert expected_result == result
        mock_redis.get.assert_called_with('commit_chunks.something')
        mock_storage.write_file.assert_called_with(
            'archive',
            f'v4/raw/2019-12-03/{repo_hash}/{commit.commitid}/{reportid}.txt',
            'Some weird value',
            gzipped=False,
            reduced_redundancy=False
        )

    def test_schedule_task_with_no_tasks(self, dbsession):
        commit = CommitFactory.create()
        commit_yaml = {}
        argument_list = []
        dbsession.add(commit)
        dbsession.flush()
        result = UploadTask().schedule_task(commit, commit_yaml, argument_list)
        assert result is None

    def test_schedule_task_with_one_task(self, dbsession, mocker):
        mocked_chain = mocker.patch('tasks.upload.chain')
        commit = CommitFactory.create()
        commit_yaml = {'codecov': {'max_report_age': '100y ago'}}
        argument_dict = {'argument_dict': 1}
        argument_list = [argument_dict]
        dbsession.add(commit)
        dbsession.flush()
        result = UploadTask().schedule_task(commit, commit_yaml, argument_list)
        assert result == mocked_chain.return_value.apply_async.return_value
        t1 = upload_processor_task.signature(
            args=({},),
            kwargs=dict(
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml=commit_yaml,
                arguments_list=argument_list
            )
        )
        t2 = upload_finisher_task.signature(
            kwargs=dict(
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml=commit_yaml
            )
        )
        mocked_chain.assert_called_with(t1, t2)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_only_commit_yaml(self, dbsession, mocker):
        commit = CommitFactory.create()
        list_top_level_files_result = Future()
        get_source_result = Future()
        repository_service = mocker.MagicMock(
            list_top_level_files=mocker.MagicMock(
                return_value=list_top_level_files_result
            ),
            get_source=mocker.MagicMock(
                return_value=get_source_result
            ),
        )
        get_source_result.set_result({
            'content': "\n".join([
                "codecov:",
                "  notify:",
                "    require_ci_to_pass: yes",
            ])
        })
        list_top_level_files_result.set_result([
            {'name': '.gitignore', 'path': '.gitignore', 'type': 'file'},
            {'name': '.travis.yml', 'path': '.travis.yml', 'type': 'file'},
            {'name': 'README.rst', 'path': 'README.rst', 'type': 'file'},
            {'name': 'awesome', 'path': 'awesome', 'type': 'folder'},
            {'name': 'codecov', 'path': 'codecov', 'type': 'file'},
            {'name': 'codecov.yaml', 'path': 'codecov.yaml', 'type': 'file'},
            {'name': 'tests', 'path': 'tests', 'type': 'folder'}
        ])
        result = await UploadTask().fetch_commit_yaml_and_possibly_store(commit, repository_service)
        expected_result = {'codecov': {'notify': {}, 'require_ci_to_pass': True}}
        assert result == expected_result
        repository_service.get_source.assert_called_with('codecov.yaml', commit.commitid)
        repository_service.list_top_level_files.assert_called_with(commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_and_base_yaml(
            self, dbsession, mock_configuration, mocker):
        mock_configuration.set_params(
            {
                'site': {
                    'sample': True
                }
            }
        )
        commit = CommitFactory.create()
        list_top_level_files_result = Future()
        get_source_result = Future()
        repository_service = mocker.MagicMock(
            list_top_level_files=mocker.MagicMock(
                return_value=list_top_level_files_result
            ),
            get_source=mocker.MagicMock(
                return_value=get_source_result
            ),
        )
        get_source_result.set_result({
            'content': "\n".join([
                "codecov:",
                "  notify:",
                "    require_ci_to_pass: yes",
            ])
        })
        list_top_level_files_result.set_result([
            {'name': '.travis.yml', 'path': '.travis.yml', 'type': 'file'},
            {'name': 'awesome', 'path': 'awesome', 'type': 'folder'},
            {'name': '.codecov.yaml', 'path': '.codecov.yaml', 'type': 'file'},
        ])
        result = await UploadTask().fetch_commit_yaml_and_possibly_store(commit, repository_service)
        expected_result = {
            'codecov': {'notify': {}, 'require_ci_to_pass': True},
            'sample': True
        }
        assert result == expected_result
        repository_service.get_source.assert_called_with('.codecov.yaml', commit.commitid)
        repository_service.list_top_level_files.assert_called_with(commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_and_repo_yaml(
            self, dbsession, mock_configuration, mocker):
        mock_configuration.set_params(
            {
                'site': {
                    'sample': True
                }
            }
        )
        commit = CommitFactory.create(
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},
            repository__branch="supeduperbranch",
            branch="supeduperbranch"
        )
        list_top_level_files_result = Future()
        get_source_result = Future()
        repository_service = mocker.MagicMock(
            list_top_level_files=mocker.MagicMock(
                return_value=list_top_level_files_result
            ),
            get_source=mocker.MagicMock(
                return_value=get_source_result
            ),
        )
        get_source_result.set_result({
            'content': "\n".join([
                "codecov:",
                "  notify:",
                "    require_ci_to_pass: yes",
            ])
        })
        list_top_level_files_result.set_result([
            {'name': '.gitignore', 'path': '.gitignore', 'type': 'file'},
            {'name': '.codecov.yaml', 'path': '.codecov.yaml', 'type': 'file'},
            {'name': 'tests', 'path': 'tests', 'type': 'folder'}
        ])
        result = await UploadTask().fetch_commit_yaml_and_possibly_store(commit, repository_service)
        expected_result = {
            'codecov': {'notify': {}, 'require_ci_to_pass': True},
            'sample': True
        }
        assert result == expected_result
        assert commit.repository.yaml == {'codecov': {'notify': {}, 'require_ci_to_pass': True}}
        repository_service.get_source.assert_called_with('.codecov.yaml', commit.commitid)
        repository_service.list_top_level_files.assert_called_with(commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_no_commit_yaml(
            self, dbsession, mock_configuration, mocker):
        mock_configuration.set_params(
            {
                'site': {
                    'sample': True
                }
            }
        )
        commit = CommitFactory.create(
            repository__owner__yaml={'coverage': {'precision': 2}},
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},
            repository__branch="supeduperbranch",
            branch="supeduperbranch"
        )
        list_top_level_files_result = Future()
        repository_service = mocker.MagicMock(
            list_top_level_files=mocker.MagicMock(
                return_value=list_top_level_files_result
            )
        )
        list_top_level_files_result.set_exception(
            TorngitClientError(404, 'fake_response', 'message')
        )
        result = await UploadTask().fetch_commit_yaml_and_possibly_store(commit, repository_service)
        expected_result = {
            'coverage': {'precision': 2},
            'codecov': {'max_report_age': '1y ago'},
            'sample': True
        }
        assert result == expected_result
        assert commit.repository.yaml == {'codecov': {'max_report_age': '1y ago'}}

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_invalid_commit_yaml(
            self, dbsession, mock_configuration, mocker):
        mock_configuration.set_params(
            {
                'site': {
                    'sample': True
                }
            }
        )
        commit = CommitFactory.create(
            repository__owner__yaml={'coverage': {'precision': 2}},
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},
            repository__branch="supeduperbranch",
            branch="supeduperbranch"
        )
        list_top_level_files_result = Future()
        get_source_result = Future()
        repository_service = mocker.MagicMock(
            list_top_level_files=mocker.MagicMock(
                return_value=list_top_level_files_result
            ),
            get_source=mocker.MagicMock(
                return_value=get_source_result
            ),
        )
        get_source_result.set_result({
            'content': "\n".join([
                "bad_key:",
                "  notify:",
                "    require_ci_to_pass: yes",
            ])
        })
        list_top_level_files_result.set_result([
            {'name': '.gitignore', 'path': '.gitignore', 'type': 'file'},
            {'name': '.codecov.yaml', 'path': '.codecov.yaml', 'type': 'file'},
            {'name': 'tests', 'path': 'tests', 'type': 'folder'}
        ])
        result = await UploadTask().fetch_commit_yaml_and_possibly_store(commit, repository_service)
        expected_result = {
            'coverage': {'precision': 2},
            'codecov': {'max_report_age': '1y ago'},
            'sample': True
        }
        assert result == expected_result
        assert commit.repository.yaml == {'codecov': {'max_report_age': '1y ago'}}
