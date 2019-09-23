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
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
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
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
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
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
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
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
        )

    @pytest.mark.asyncio
    async def test_upload_task_proper_parent(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
        mocked_1 = mocker.patch('tasks.upload.chain')
        redis_queue = []
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [False]

        parent_commit = CommitFactory.create(
            message='',
            commitid='c5b67303452bbff57cc1f49984339cde39eb1db5',
            repository__owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
        )

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
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
            f"upload_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
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
