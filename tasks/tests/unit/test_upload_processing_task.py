from pathlib import Path

import pytest
import celery

from tasks.upload_processor import UploadProcessorTask
from database.tests.factories import CommitFactory
from helpers.exceptions import ReportExpiredException
from services.archive import ArchiveService

here = Path(__file__)


class TestUploadProcessorTask(object):

    @pytest.mark.asyncio
    async def test_upload_processor_task_call(self, mocker, test_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
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
                    'd': commit.report['sessions']['0']['d']  # This is not deterministic
                }
            }
        }
        assert commit.report == expected_generated_report
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
    async def test_upload_task_call_existing_chunks(self, mocker, test_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
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
    async def test_upload_task_call_with_try_later(self, mocker, test_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
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
            max_retries=3
        )

    @pytest.mark.asyncio
    async def test_upload_task_call_with_expired_report(self, mocker, test_configuration, dbsession, mock_repo_provider, mock_storage, mock_redis):
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
