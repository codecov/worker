from pathlib import Path
from asyncio import Future
import pytest
import celery
from redis.exceptions import LockError
from torngit.exceptions import TorngitObjectNotFoundError
from covreports.resources import Report, ReportFile, ReportLine, ReportTotals

from tasks.upload_processor import UploadProcessorTask
from database.tests.factories import CommitFactory
from helpers.exceptions import (
    ReportExpiredException, ReportEmptyError, RepositoryWithoutValidBotError
)
from services.archive import ArchiveService

here = Path(__file__)


class TestUploadProcessorTask(object):

    @pytest.mark.asyncio
    async def test_upload_processor_task_call(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch.object(ArchiveService, 'read_chunks')
        mocked_1.return_value = None
        with open(here.parent.parent / 'samples' / 'sample_uploaded_report_1.txt') as f:
            content = f.read()
            mock_storage.read_file.return_value.decode.return_value = content
        url = 'v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt'
        redis_queue = [
            {
                'url': url
            }
        ]
        mocked_3 = mocker.patch.object(UploadProcessorTask, 'app')
        mocked_3.send_task.return_value = True

        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov'
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
            arguments_list=redis_queue
        )
        mock_storage.read_file.assert_called_with('archive', url)
        expected_result = {
            'processings_so_far': [
                {
                    'arguments': {'url': url},
                    'successful': True
                }
            ]
        }
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'
        expected_generated_report = {
            'files': {
                'awesome/__init__.py': [
                    0,
                    [0, 14, 10, 4, 0, '71.42857', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 14, 10, 4, 0, '71.42857', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    [
                        0, 4, 4, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0
                    ]
                ],
                'tests/__init__.py': [
                    1,
                    [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    None
                ],
                'tests/test_sample.py': [
                    2,
                    [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    None
                ]
            },
            'sessions': {
                '0': {
                    'N': None,
                    'a': url,
                    'c': None,
                    'e': None,
                    'f': None,
                    'j': None,
                    'n': None,
                    'p': None,
                    't': [3, 24, 19, 5, 0, '79.16667', 0, 0, 0, 0, 0, 0, 0],
                    'u': None,
                    'd': commit.report_json['sessions']['0']['d']  # This is not deterministic
                }
            }
        }
        assert commit.report_json == expected_generated_report
        mocked_1.assert_called_with(commit.commitid)
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_processing_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=30, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_call_existing_chunks(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch.object(ArchiveService, 'read_chunks')
        with open(here.parent.parent / 'samples' / 'sample_chunks_1.txt') as f:
            content = f.read()
            mocked_1.return_value = content
        with open(here.parent.parent / 'samples' / 'sample_uploaded_report_1.txt') as f:
            content = f.read()
            mock_storage.read_file.return_value.decode.return_value = content
        url = 'v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt'
        redis_queue = [
            {
                'url': url
            }
        ]
        mocked_3 = mocker.patch.object(UploadProcessorTask, 'app')
        mocked_3.send_task.return_value = True

        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
            arguments_list=redis_queue
        )
        mock_storage.read_file.assert_called_with('archive', url)
        expected_result = {
            'processings_so_far': [
                {
                    'arguments': {'url': url},
                    'successful': True
                }
            ]
        }
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'
        mocked_1.assert_called_with(commit.commitid)
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_processing_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=30, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_call_with_try_later(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch.object(ArchiveService, 'read_chunks')
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(UploadProcessorTask, 'do_process_individual_report')
        mocked_2.side_effect = Exception()
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_3 = mocker.patch.object(UploadProcessorTask, 'retry')
        mocked_3.side_effect = celery.exceptions.Retry()
        mocked_4 = mocker.patch.object(UploadProcessorTask, 'app')
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        redis_queue = [
            {
                'url': 'url'
            }
        ]
        with pytest.raises(celery.exceptions.Retry):
            await UploadProcessorTask().run_async(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=redis_queue
            )
        mocked_2.assert_called_with(
            mocker.ANY, mock_redis, {}, commit, mocker.ANY, False, url='url'
        )
        mocked_3.assert_called_with(
            countdown=20,
            max_retries=5,
            queue='new_tasks'
        )

    @pytest.mark.asyncio
    async def test_upload_task_call_with_redis_lock_unobtainable(self, mocker, mock_configuration, dbsession, mock_redis):
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_3 = mocker.patch.object(UploadProcessorTask, 'retry')
        mocked_3.side_effect = celery.exceptions.Retry()
        mocked_4 = mocker.patch.object(UploadProcessorTask, 'app')
        mocked_4.send_task.return_value = True
        mock_redis.lock.return_value.__enter__.side_effect = LockError()
        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        with pytest.raises(celery.exceptions.Retry):
            await UploadProcessorTask().run_async(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=[{'url': 'url'}]
            )
        mocked_3.assert_called_with(
            countdown=20,
            max_retries=5,
            queue='new_tasks'
        )

    @pytest.mark.asyncio
    async def test_upload_task_call_with_expired_report(self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage, mock_redis):
        mocked_1 = mocker.patch.object(ArchiveService, 'read_chunks')
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(UploadProcessorTask, 'do_process_individual_report')
        false_report = mocker.MagicMock(
            to_database=mocker.MagicMock(
                return_value=({}, '{}')
            )
        )
        mocked_2.side_effect = [false_report, ReportExpiredException()]
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_4 = mocker.patch.object(UploadProcessorTask, 'app')
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        redis_queue = [
            {
                'url': 'url',
                'what': 'huh'
            },
            {
                'url': 'url2',
                'extra_param': 45
            },
        ]
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
            arguments_list=redis_queue
        )
        expected_result = {
            'processings_so_far': [
                {
                    'arguments': {'url': 'url', 'what': 'huh'},
                    'successful': True
                },
                {
                    'arguments': {'extra_param': 45, 'url': 'url2'},
                    'error_type': 'report_expired',
                    'report': None,
                    'should_retry': False,
                    'successful': False
                }
            ]
        }
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_upload_task_call_with_empty_report(self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage, mock_redis):
        mocked_1 = mocker.patch.object(ArchiveService, 'read_chunks')
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(UploadProcessorTask, 'do_process_individual_report')
        false_report = mocker.MagicMock(
            to_database=mocker.MagicMock(
                return_value=({}, '{}')
            )
        )
        mocked_2.side_effect = [false_report, ReportEmptyError()]
        mocked_4 = mocker.patch.object(UploadProcessorTask, 'app')
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        redis_queue = [
            {
                'url': 'url',
                'what': 'huh'
            },
            {
                'url': 'url2',
                'extra_param': 45
            },
        ]
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
            arguments_list=redis_queue
        )
        expected_result = {
            'processings_so_far': [
                {
                    'arguments': {'url': 'url', 'what': 'huh'},
                    'successful': True
                },
                {
                    'arguments': {'extra_param': 45, 'url': 'url2'},
                    'error_type': 'report_empty',
                    'report': None,
                    'should_retry': False,
                    'successful': False
                }
            ]
        }
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_save_report_results_apply_diff_not_there(self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage):
        commit = CommitFactory.create(
            message='',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        report = Report()
        report_file_1 = ReportFile('path/to/first.py')
        report_file_2 = ReportFile('to/second/path.py')
        report_line_1 = ReportLine(coverage=1, sessions=[[0, 1]])
        report_line_2 = ReportLine(coverage=0, sessions=[[0, 0]])
        report_line_3 = ReportLine(coverage=1, sessions=[[0, 1]])
        report_file_1.append(10, report_line_1)
        report_file_1.append(12, report_line_2)
        report_file_2.append(12, report_line_3)
        report.append(report_file_1)
        report.append(report_file_2)
        chunks_archive_service = ArchiveService(commit.repository)
        f = Future()
        f.set_exception(TorngitObjectNotFoundError('response', 'message'))
        mock_repo_provider.get_commit_diff.return_value = f
        result = await UploadProcessorTask().save_report_results(
            db_session=dbsession,
            chunks_archive_service=chunks_archive_service,
            repository=commit.repository,
            commit=commit,
            report=report,
            pr=None
        )
        expected_result = {
            'url': f'v4/repos/{chunks_archive_service.storage_hash}/commits/{commit.commitid}/chunks.txt'
        }
        assert expected_result == result
        assert report.diff_totals is None

    @pytest.mark.asyncio
    async def test_save_report_results_apply_diff_no_bot(self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage):
        commit = CommitFactory.create(
            message='',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry for the timebomb
        )
        mock_get_repo_service = mocker.patch('tasks.upload_processor.get_repo_provider_service')
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        dbsession.add(commit)
        dbsession.flush()
        report = Report()
        report_file_1 = ReportFile('path/to/first.py')
        report_file_2 = ReportFile('to/second/path.py')
        report_line_1 = ReportLine(coverage=1, sessions=[[0, 1]])
        report_line_2 = ReportLine(coverage=0, sessions=[[0, 0]])
        report_line_3 = ReportLine(coverage=1, sessions=[[0, 1]])
        report_file_1.append(10, report_line_1)
        report_file_1.append(12, report_line_2)
        report_file_2.append(12, report_line_3)
        report.append(report_file_1)
        report.append(report_file_2)
        chunks_archive_service = ArchiveService(commit.repository)
        result = await UploadProcessorTask().save_report_results(
            db_session=dbsession,
            chunks_archive_service=chunks_archive_service,
            repository=commit.repository,
            commit=commit,
            report=report,
            pr=None
        )
        expected_result = {
            'url': f'v4/repos/{chunks_archive_service.storage_hash}/commits/{commit.commitid}/chunks.txt'
        }
        assert expected_result == result
        assert report.diff_totals is None

    @pytest.mark.asyncio
    async def test_save_report_results_apply_diff_valid(self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage):
        commit = CommitFactory.create(
            message='',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        report = Report()
        report_file_1 = ReportFile('path/to/first.py')
        report_file_2 = ReportFile('to/second/path.py')
        report_line_1 = ReportLine(coverage=1, sessions=[[0, 1]])
        report_line_2 = ReportLine(coverage=0, sessions=[[0, 0]])
        report_line_3 = ReportLine(coverage=1, sessions=[[0, 1]])
        report_file_1.append(10, report_line_1)
        report_file_1.append(12, report_line_2)
        report_file_2.append(12, report_line_3)
        report.append(report_file_1)
        report.append(report_file_2)
        chunks_archive_service = ArchiveService(commit.repository)
        f = Future()
        f.set_result({
            'files': {
                'path/to/first.py': {
                    'type': 'modified',
                    'before': None,
                    'segments': [
                        {
                            'header': ['9', '3', '9', '5'],
                            'lines': ['+sudo: false', '+', ' language: python', ' ', ' python:']
                        }
                    ],
                    'stats': {'added': 2, 'removed': 0}
                }
            }
        })
        mock_repo_provider.get_commit_diff.return_value = f
        result = await UploadProcessorTask().save_report_results(
            db_session=dbsession,
            chunks_archive_service=chunks_archive_service,
            commit=commit,
            repository=commit.repository,
            report=report,
            pr=None
        )
        expected_result = {
            'url': f'v4/repos/{chunks_archive_service.storage_hash}/commits/{commit.commitid}/chunks.txt'
        }
        assert expected_result == result
        expected_diff_totals = ReportTotals(
            files=1,
            lines=1,
            hits=1,
            misses=0,
            partials=0,
            coverage='100',
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0
        )
        assert report.diff_totals == expected_diff_totals
