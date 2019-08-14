import json
from pathlib import Path

import pytest

from tasks.upload import UploadTask
from tasks.upload_processor import upload_processor_task
from tasks.upload_finisher import upload_finisher_task
from database.tests.factories import CommitFactory

here = Path(__file__)


class TestUploadTask(object):

    @pytest.mark.asyncio
    async def test_upload_task_call(self, mocker, test_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
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
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {}
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'
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
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
        )
