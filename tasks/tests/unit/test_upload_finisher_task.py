import json
from pathlib import Path
import os

import pytest

from tasks.upload_finisher import UploadFinisherTask
from database.tests.factories import CommitFactory

here = Path(__file__)


class TestUploadFinisherTask(object):

    @pytest.mark.asyncio
    async def test_upload_finisher_task_call(self, mocker, mock_configuration, dbsession, codecov_vcr, mock_storage, mock_redis):
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
        previous_results = {
            'processings_so_far': [
                {
                    'arguments': {'url': url},
                    'successful': True
                }
            ]
        }
        result = await UploadFinisherTask().run_async(
            dbsession, previous_results,
            repoid=commit.repoid, commitid=commit.commitid, commit_yaml={}
        )
        expected_result = {'notifications_called': True}
        assert expected_result == result
        assert commit.message == 'dsidsahdsahdsa'

        mock_redis.lock.assert_called_with(
            f"upload_finisher_lock_{commit.repoid}_{commit.commitid}", blocking_timeout=30, timeout=300
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications(self, dbsession):
        commit_yaml = {'codecov': {'max_report_age': '1y ago'}}
        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            'processings_so_far': [
                {
                    'arguments': {'url': 'url'},
                    'successful': True
                }
            ]
        }
        assert UploadFinisherTask().should_call_notifications(
             commit, commit_yaml, processing_results
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_no_successful_reports(self, dbsession):
        commit_yaml = {'codecov': {'max_report_age': '1y ago'}}
        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            'processings_so_far': 12 * [
                {
                    'arguments': {'url': 'url'},
                    'successful': False
                }
            ]
        }
        assert not UploadFinisherTask().should_call_notifications(
             commit, commit_yaml, processing_results
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_not_enough_builds(self, dbsession):
        commit_yaml = {'codecov': {'notify': {'after_n_builds': 9}}}
        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml=commit_yaml,
            report_json={'sessions': {str(n): {'a': str(f'http://{n}')} for n in range(8)}}
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            'processings_so_far': 9 * [
                {
                    'arguments': {'url': 'url'},
                    'successful': True
                }
            ]
        }
        assert not UploadFinisherTask().should_call_notifications(
             commit, commit_yaml, processing_results
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_more_than_enough_builds(self, dbsession):
        commit_yaml = {'codecov': {'notify': {'after_n_builds': 9}}}
        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml=commit_yaml,
            report_json={'sessions': {str(n): {'a': str(f'http://{n}')} for n in range(10)}}
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            'processings_so_far': 2 * [
                {
                    'arguments': {'url': 'url'},
                    'successful': True
                }
            ]
        }
        assert UploadFinisherTask().should_call_notifications(
             commit, commit_yaml, processing_results
        )

    @pytest.mark.asyncio
    async def test_finish_reports_processing(self, dbsession, mocker):
        mocker.patch.object(UploadFinisherTask, 'should_send_notify_task_to_new_worker', return_value=True)
        commit_yaml = {}
        mocked_app = mocker.patch.object(UploadFinisherTask, 'app')
        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml=commit_yaml,
        )
        processing_results = {'processings_so_far': [{'successful': True}]}
        dbsession.add(commit)
        dbsession.flush()
        res = await UploadFinisherTask().finish_reports_processing(
             dbsession, commit, commit_yaml, processing_results
        )
        assert res == {'notifications_called': True}
        mocked_app.tasks['app.tasks.notify.Notify'].apply_async.assert_called_with(
            queue='new_tasks',
            kwargs=dict(
                commitid=commit.commitid,
                current_yaml=commit_yaml,
                repoid=commit.repoid
            )
        )
        assert mocked_app.send_task.call_count == 1

    def test_should_send_notify_task_to_new_worker(self, dbsession, mocker):
        first_commit = CommitFactory.create()
        second_commit = CommitFactory.create()
        third_commit = CommitFactory.create(repository=first_commit.repository)
        fourth_commit = CommitFactory.create(repository__owner=first_commit.repository.owner)
        fifth_commit = CommitFactory.create()
        dbsession.add(first_commit)
        dbsession.add(second_commit)
        dbsession.add(third_commit)
        dbsession.add(fourth_commit)
        dbsession.add(fifth_commit)
        dbsession.flush()
        whitelist = f'{first_commit.repository.ownerid} {fifth_commit.repository.ownerid}'
        mocker.patch.dict(os.environ, {'NOTIFY_WHITELISTED_OWNERS': whitelist})
        task = UploadFinisherTask()
        assert task.should_send_notify_task_to_new_worker(first_commit)
        assert not task.should_send_notify_task_to_new_worker(second_commit)
        assert task.should_send_notify_task_to_new_worker(third_commit)
        assert task.should_send_notify_task_to_new_worker(fourth_commit)
        assert task.should_send_notify_task_to_new_worker(fifth_commit)


    @pytest.mark.asyncio
    async def test_finish_reports_processing_legacy_worker(self, dbsession, mocker):
        mocker.patch.object(UploadFinisherTask, 'should_send_notify_task_to_new_worker', return_value=False)
        commit_yaml = {}
        mocked_app = mocker.patch.object(UploadFinisherTask, 'app')
        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml=commit_yaml,
        )
        processing_results = {'processings_so_far': [{'successful': True}]}
        dbsession.add(commit)
        dbsession.flush()
        res = await UploadFinisherTask().finish_reports_processing(
             dbsession, commit, commit_yaml, processing_results
        )
        assert res == {'notifications_called': True}
        mocked_app.send_task.assert_called_with(
            'app.tasks.notify.Notify',
            args=None,
            kwargs=dict(
                commitid=commit.commitid,
                repoid=commit.repoid
            )
        )
        assert mocked_app.send_task.call_count == 2
        assert not mocked_app.tasks['app.tasks.notify.Notify'].apply_async.called

    @pytest.mark.asyncio
    async def test_finish_reports_processing_no_notification(self, dbsession, mocker):
        mocker.patch.object(UploadFinisherTask, 'should_send_notify_task_to_new_worker', return_value=False)
        commit_yaml = {}
        mocked_app = mocker.patch.object(UploadFinisherTask, 'app')
        commit = CommitFactory.create(
            message='dsidsahdsahdsa',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8',
            repository__owner__username='ThiagoCodecov',
            repository__yaml=commit_yaml,
        )
        processing_results = {'processings_so_far': [{'successful': False}]}
        dbsession.add(commit)
        dbsession.flush()
        res = await UploadFinisherTask().finish_reports_processing(
             dbsession, commit, commit_yaml, processing_results
        )
        assert res == {'notifications_called': False}
        assert mocked_app.send_task.call_count == 1
        assert not mocked_app.tasks['app.tasks.notify.Notify'].apply_async.called
