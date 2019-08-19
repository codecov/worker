import json
from pathlib import Path

import pytest

from tasks.upload_finisher import UploadFinisherTask
from database.tests.factories import CommitFactory

here = Path(__file__)


class TestUploadFinisherTask(object):

    @pytest.mark.asyncio
    async def test_upload_finisher_task_call(self, mocker, test_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        url = 'v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt'
        redis_queue = [
            {
                'url': url
            }
        ]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadFinisherTask, 'app')
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = jsonified_redis_queue

        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
        )
        dbsession.add(commit)
        dbsession.flush()
        previous_results = {}
        result = await UploadFinisherTask().run_async(
            dbsession, previous_results,
            repoid=commit.repoid, commitid=commit.commitid, commit_yaml={}
        )
        expected_result = {}
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'

        mock_redis.lock.assert_called_with(
            f"upload_finisher_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
        )
