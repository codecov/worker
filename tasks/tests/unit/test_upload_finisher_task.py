import json
from pathlib import Path
from unittest.mock import ANY, call

import pytest
from shared.yaml import UserYaml

from database.tests.factories import (
    CommitFactory,
    PullFactory,
    ReportFactory,
    RepositoryFactory,
    UploadFactory,
)
from helpers.checkpoint_logger import CheckpointLogger, _kwargs_key
from helpers.checkpoint_logger.flows import UploadFlow
from tasks.upload_finisher import ReportService, UploadFinisherTask

here = Path(__file__)


def _create_checkpoint_logger(mocker):
    mocker.patch(
        "helpers.checkpoint_logger._get_milli_timestamp",
        side_effect=[1337, 9001, 10000, 15000, 20000, 25000],
    )
    checkpoints = CheckpointLogger(UploadFlow)
    checkpoints.log(UploadFlow.UPLOAD_TASK_BEGIN)
    checkpoints.log(UploadFlow.PROCESSING_BEGIN)
    checkpoints.log(UploadFlow.INITIAL_PROCESSING_COMPLETE)
    return checkpoints


class TestUploadFinisherTask(object):
    @pytest.mark.asyncio
    async def test_upload_finisher_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        mock_checkpoint_submit,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        redis_queue = [{"url": url}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadFinisherTask, "app")
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = jsonified_redis_queue

        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            branch="thisbranch",
            ci_passed=True,
            repository__branch="thisbranch",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__owner__service="github",
            author__service="github",
            notified=True,
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry, this is a timebomb now
        )
        dbsession.add(commit)
        dbsession.flush()
        previous_results = {
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}]
        }

        checkpoints = _create_checkpoint_logger(mocker)
        kwargs = {_kwargs_key(UploadFlow): checkpoints.data}
        result = await UploadFinisherTask().run_async(
            dbsession,
            previous_results,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
            **kwargs,
        )
        assert commit.notified is False
        expected_result = {"notifications_called": True}
        assert expected_result == result
        dbsession.refresh(commit)
        assert commit.message == "dsidsahdsahdsa"

        mock_redis.lock.assert_called_with(
            f"upload_finisher_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

        assert checkpoints.data == {
            UploadFlow.UPLOAD_TASK_BEGIN: 1337,
            UploadFlow.PROCESSING_BEGIN: 9001,
            UploadFlow.INITIAL_PROCESSING_COMPLETE: 10000,
            UploadFlow.BATCH_PROCESSING_COMPLETE: 15000,
            UploadFlow.PROCESSING_COMPLETE: 20000,
        }
        calls = [
            call(
                "batch_processing_duration",
                UploadFlow.INITIAL_PROCESSING_COMPLETE,
                UploadFlow.BATCH_PROCESSING_COMPLETE,
            ),
            call(
                "total_processing_duration",
                UploadFlow.PROCESSING_BEGIN,
                UploadFlow.PROCESSING_COMPLETE,
            ),
        ]
        mock_checkpoint_submit.assert_has_calls(calls)

    @pytest.mark.asyncio
    async def test_upload_finisher_task_call_no_author(
        self, mocker, mock_configuration, dbsession, mock_storage, mock_redis
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        redis_queue = [{"url": url}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadFinisherTask, "app")
        mock_finish_reports_processing = mocker.patch.object(
            UploadFinisherTask, "finish_reports_processing"
        )
        mock_finish_reports_processing.return_value = {"notifications_called": True}
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = jsonified_redis_queue

        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            author=None,
            branch="thisbranch",
            ci_passed=True,
            repository__branch="thisbranch",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry, this is a timebomb now
        )
        dbsession.add(commit)
        dbsession.flush()
        previous_results = {
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}]
        }
        result = await UploadFinisherTask().run_async(
            dbsession,
            previous_results,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
        )
        expected_result = {"notifications_called": True}
        assert expected_result == result
        dbsession.refresh(commit)
        assert commit.message == "dsidsahdsahdsa"

        mock_redis.lock.assert_called_with(
            f"upload_finisher_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.asyncio
    async def test_upload_finisher_task_call_different_branch(
        self, mocker, mock_configuration, dbsession, mock_storage, mock_redis
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        redis_queue = [{"url": url}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadFinisherTask, "app")
        mock_finish_reports_processing = mocker.patch.object(
            UploadFinisherTask, "finish_reports_processing"
        )
        mock_finish_reports_processing.return_value = {"notifications_called": True}
        mocked_3.send_task.return_value = True
        mock_redis.exists.side_effect = [True, False]
        mock_redis.lpop.side_effect = jsonified_redis_queue

        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            branch="other_branch",
            ci_passed=True,
            repository__branch="thisbranch",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry, this is a timebomb now
        )
        dbsession.add(commit)
        dbsession.flush()
        previous_results = {
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}]
        }
        result = await UploadFinisherTask().run_async(
            dbsession,
            previous_results,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
        )
        expected_result = {"notifications_called": True}
        assert expected_result == result
        dbsession.refresh(commit)
        assert commit.message == "dsidsahdsahdsa"

        mock_redis.lock.assert_called_with(
            f"upload_finisher_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications(self, dbsession):
        commit_yaml = {"codecov": {"max_report_age": "1y ago"}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            "processings_so_far": [{"arguments": {"url": "url"}, "successful": True}]
        }
        assert UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results, None
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_local_upload(self, dbsession):
        commit_yaml = {"codecov": {"max_report_age": "1y ago"}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {}
        assert not UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results, "local_report1"
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_manual_trigger(self, dbsession):
        commit_yaml = {"codecov": {"notify": {"manual_trigger": True}}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="aabbcc",
            repository__owner__username="Codecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {}
        assert not UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results, None
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_manual_trigger_off(self, dbsession):
        commit_yaml = {
            "codecov": {"max_report_age": "1y ago", "notify": {"manual_trigger": False}}
        }
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            "processings_so_far": [{"arguments": {"url": "url"}, "successful": True}]
        }
        assert UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results, None
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_no_successful_reports(self, dbsession):
        commit_yaml = {"codecov": {"max_report_age": "1y ago"}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            "processings_so_far": 12
            * [{"arguments": {"url": "url"}, "successful": False}]
        }
        assert not UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results, None
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_not_enough_builds(self, dbsession, mocker):
        commit_yaml = {"codecov": {"notify": {"after_n_builds": 9}}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)

        mocked_report = mocker.patch.object(
            ReportService, "get_existing_report_for_commit"
        )
        mocked_report.return_value = mocker.MagicMock(
            sessions=[mocker.MagicMock()] * 8
        )  # 8 sessions

        processing_results = {
            "processings_so_far": 9
            * [{"arguments": {"url": "url"}, "successful": True}]
        }
        assert not UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results, None
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_more_than_enough_builds(
        self, dbsession, mocker
    ):
        commit_yaml = {"codecov": {"notify": {"after_n_builds": 9}}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)

        mocked_report = mocker.patch.object(
            ReportService, "get_existing_report_for_commit"
        )
        mocked_report.return_value = mocker.MagicMock(
            sessions=[mocker.MagicMock()] * 10
        )  # 10 sessions

        processing_results = {
            "processings_so_far": 2
            * [{"arguments": {"url": "url"}, "successful": True}]
        }
        assert UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results, None
        )

    @pytest.mark.asyncio
    async def test_finish_reports_processing(self, dbsession, mocker):
        commit_yaml = {}
        mocked_app = mocker.patch.object(UploadFinisherTask, "app")
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        processing_results = {"processings_so_far": [{"successful": True}]}
        dbsession.add(commit)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        res = await UploadFinisherTask().finish_reports_processing(
            dbsession,
            commit,
            UserYaml(commit_yaml),
            processing_results,
            None,
            checkpoints,
        )
        assert res == {"notifications_called": True}
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_called_with(
            kwargs={
                "commitid": commit.commitid,
                "current_yaml": commit_yaml,
                "repoid": commit.repoid,
                _kwargs_key(UploadFlow): ANY,
            },
        )
        assert mocked_app.send_task.call_count == 0

    @pytest.mark.asyncio
    async def test_finish_reports_processing_with_pull(self, dbsession, mocker):
        commit_yaml = {}
        mocked_app = mocker.patch.object(
            UploadFinisherTask,
            "app",
            tasks={
                "app.tasks.notify.Notify": mocker.MagicMock(),
                "app.tasks.pulls.Sync": mocker.MagicMock(),
                "app.tasks.compute_comparison.ComputeComparison": mocker.MagicMock(),
            },
        )
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            owner__username="ThiagoCodecov",
            yaml=commit_yaml,
        )
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(repository=repository)
        compared_to = CommitFactory.create(repository=repository)
        pull.compared_to = compared_to.commitid
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository=repository,
            pullid=pull.pullid,
        )
        processing_results = {"processings_so_far": [{"successful": True}]}
        dbsession.add(commit)
        dbsession.add(compared_to)
        dbsession.add(pull)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        res = await UploadFinisherTask().finish_reports_processing(
            dbsession,
            commit,
            UserYaml(commit_yaml),
            processing_results,
            None,
            checkpoints,
        )
        assert res == {"notifications_called": True}
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_called_with(
            kwargs={
                "commitid": commit.commitid,
                "current_yaml": commit_yaml,
                "repoid": commit.repoid,
                _kwargs_key(UploadFlow): ANY,
            },
        )
        mocked_app.tasks["app.tasks.pulls.Sync"].apply_async.assert_called_with(
            kwargs={
                "pullid": pull.pullid,
                "repoid": pull.repoid,
                "should_send_notifications": False,
            }
        )
        assert mocked_app.send_task.call_count == 0

        mocked_app.tasks[
            "app.tasks.compute_comparison.ComputeComparison"
        ].apply_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_finish_reports_processing_no_notification(self, dbsession, mocker):
        commit_yaml = {}
        mocked_app = mocker.patch.object(UploadFinisherTask, "app")
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        processing_results = {"processings_so_far": [{"successful": False}]}
        dbsession.add(commit)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        res = await UploadFinisherTask().finish_reports_processing(
            dbsession,
            commit,
            UserYaml(commit_yaml),
            processing_results,
            None,
            checkpoints,
        )
        assert res == {"notifications_called": False}
        assert mocked_app.send_task.call_count == 0
        assert not mocked_app.tasks["app.tasks.notify.Notify"].apply_async.called

    @pytest.mark.asyncio
    async def test_upload_finisher_task_calls_save_commit_measurements(
        self, mocker, dbsession, mock_redis
    ):
        mocked_save_commit_measurements = mocker.patch(
            "tasks.upload_finisher.save_commit_measurements"
        )

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()

        await UploadFinisherTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
        )

        mocked_save_commit_measurements.assert_called_once_with(commit)
