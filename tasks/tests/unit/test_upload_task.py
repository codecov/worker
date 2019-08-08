import json
from pathlib import Path

import pytest
import celery

from tasks.upload import UploadTask
from database.tests.factories import CommitFactory
from services.archive import ArchiveService

here = Path(__file__)


class TestUploadTask(object):

    @pytest.mark.asyncio
    async def test_upload_task_call(self, mocker, test_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
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
        redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = redis_queue
        mocked_invalidate_caches = mocker.patch.object(UploadTask, 'invalidate_caches')
        mocked_invalidate_caches.return_value = True

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
            repository__repoid=2,
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        mock_storage.read_file.assert_called_with('archive', url)
        expected_result = {
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
                    'u': None
                }
            }
        }

        assert expected_result['files']['awesome/__init__.py'] == result['files']['awesome/__init__.py']
        assert expected_result['files'] == result['files']
        del result['sessions']['0']['d']  # This is not deterministic
        assert expected_result['sessions'] == result['sessions']
        assert commit.message == 'dsidsahdsahdsa'
        mocked_1.assert_called_with(commit.commitid)
        mock_redis.lpop.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
        )
        mocked_invalidate_caches.assert_called_with(mocker.ANY, commit)

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
        redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = redis_queue
        mocked_invalidate_caches = mocker.patch.object(UploadTask, 'invalidate_caches')
        mocked_invalidate_caches.return_value = True

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        mock_storage.read_file.assert_called_with('archive', url)
        expected_result = {
            'files': {
                'awesome/__init__.py': [
                    2,
                    [0, 16, 13, 3, 0, '81.25000', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 10, 8, 2, 0, '80.00000', 0, 0, 0, 0, 0, 0, 0],
                        [0, 14, 10, 4, 0, '71.42857', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    [
                        0, 4, 4, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0
                    ]
                ],
                'tests/__init__.py': [
                    0,
                    [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0],
                        [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    None
                ],
                'tests/test_sample.py': [
                    1,
                    [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0],
                        [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    None
                ]
            },
            'sessions': {
                '0': {
                    'N': None,
                    'a': 'v4/raw/2019-01-10/4434BC2A2EC4FCA57F77B473D83F928C/abf6d4df662c47e32460020ab14abf9303581429/9ccc55a1-8b41-4bb1-a946-ee7a33a7fb56.txt',
                    'c': None,
                    'e': None,
                    'f': None,
                    'j': None,
                    'n': None,
                    'p': None,
                    't': [3, 20, 17, 3, 0, '85.00000', 0, 0, 0, 0, 0, 0, 0],
                    'u': None
                },
                '1': {
                    'N': None,
                    'a': url,
                    'c': None,
                    'e': None,
                    'f': None,
                    'j': None,
                    'n': None,
                    'p': None,
                    't': [3, 24, 19, 5, 0, '79.16667', 0, 0, 0, 0, 0, 0, 0],
                    'u': None
                }
            }
        }

        assert expected_result['files']['awesome/__init__.py'] == result['files']['awesome/__init__.py']
        assert expected_result['files']['tests/test_sample.py'] == result['files']['tests/test_sample.py']
        assert expected_result['files']['tests/__init__.py'] == result['files']['tests/__init__.py']
        assert expected_result['files'] == result['files']
        del result['sessions']['0']['d']  # This is not deterministic
        del result['sessions']['1']['d']  # This is not deterministic
        assert expected_result['sessions'] == result['sessions']
        assert commit.message == 'dsidsahdsahdsa'
        mocked_1.assert_called_with(commit.commitid)
        mock_redis.lpop.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mock_redis.exists.assert_called_with('testuploads/%s/%s' % (commit.repoid, commit.commitid))
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
        )
        mocked_invalidate_caches.assert_called_with(mocker.ANY, commit)

    @pytest.mark.asyncio
    async def test_upload_task_call_with_try_later(self, mocker, test_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch.object(ArchiveService, 'read_chunks')
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(UploadTask, 'process_individual_report')
        mocked_2.side_effect = Exception()
        mocked_4 = mocker.patch.object(UploadTask, 'app')
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
        )
        dbsession.add(commit)
        dbsession.flush()
        redis_queue = [
            {
                'url': 'url'
            }
        ]
        redis_queue = [json.dumps(x) for x in redis_queue]
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = redis_queue
        with pytest.raises(celery.exceptions.Retry):
            await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        mocked_2.assert_called_with(
            mocker.ANY, mock_redis, mocker.ANY, commit, mocker.ANY, False, url='url'
        )
        mock_redis.rpush.assert_called_with(
            'testuploads/5/abf6d4df662c47e32460020ab14abf9303581429', '{"url": "url"}'
        )
