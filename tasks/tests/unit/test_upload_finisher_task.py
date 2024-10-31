import json
from pathlib import Path
from unittest.mock import ANY, call

import pytest
from celery.exceptions import Retry
from redis.exceptions import LockError
from shared.celery_config import timeseries_save_commit_measurements_task_name
from shared.yaml import UserYaml

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from helpers.checkpoint_logger import CheckpointLogger, _kwargs_key
from helpers.checkpoint_logger.flows import UploadFlow
from tasks.upload_finisher import (
    ReportService,
    ShouldCallNotifyResult,
    UploadFinisherTask,
    get_processing_results,
)

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


def test_results_arg_old_no_id():
    results = get_processing_results(
        [
            {
                "processings_so_far": [
                    {"arguments": {"foo": "bar"}, "successful": True}
                ],
                "parallel_incremental_result": {"upload_pk": 123},
            }
        ]
    )
    assert results == [
        {"upload_id": 123, "arguments": {"foo": "bar"}, "successful": True}
    ]


def test_results_arg_old_with_id():
    results = get_processing_results(
        [
            {
                "processings_so_far": [
                    {"upload_id": 123, "arguments": {"foo": "bar"}, "successful": True}
                ],
                "parallel_incremental_result": {"upload_pk": "something else entirely"},
            }
        ]
    )
    assert results == [
        {"upload_id": 123, "arguments": {"foo": "bar"}, "successful": True}
    ]


def test_results_arg_new():
    results = get_processing_results(
        [{"upload_id": 123, "arguments": {"foo": "bar"}, "successful": True}]
    )
    assert results == [
        {"upload_id": 123, "arguments": {"foo": "bar"}, "successful": True}
    ]


class TestUploadFinisherTask(object):
    @pytest.mark.django_db(databases={"default"})
    def test_upload_finisher_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_checkpoint_submit,
        mock_repo_provider,
    ):
        mocker.patch("tasks.upload_finisher.load_intermediate_reports", return_value=[])
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        mocked_3 = mocker.patch.object(
            UploadFinisherTask, "app", conf=mocker.MagicMock(task_time_limit=123)
        )
        mocked_3.send_task.return_value = True

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
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}],
            "parallel_incremental_result": {"upload_pk": 0},
        }

        checkpoints = _create_checkpoint_logger(mocker)
        checkpoints_data = json.loads(json.dumps(checkpoints.data))
        kwargs = {_kwargs_key(UploadFlow): checkpoints_data}
        result = UploadFinisherTask().run_impl(
            dbsession,
            [previous_results],
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

    @pytest.mark.django_db(databases={"default"})
    def test_upload_finisher_task_call_no_author(
        self, mocker, mock_configuration, dbsession, mock_storage, mock_repo_provider
    ):
        mocker.patch("tasks.upload_finisher.load_intermediate_reports", return_value=[])
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        mocked_3 = mocker.patch.object(
            UploadFinisherTask, "app", conf=mocker.MagicMock(task_time_limit=123)
        )
        mock_finish_reports_processing = mocker.patch.object(
            UploadFinisherTask, "finish_reports_processing"
        )
        mock_finish_reports_processing.return_value = {"notifications_called": True}
        mocked_3.send_task.return_value = True

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
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}],
            "parallel_incremental_result": {"upload_pk": 0},
        }
        result = UploadFinisherTask().run_impl(
            dbsession,
            [previous_results],
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
        )
        expected_result = {"notifications_called": True}
        assert expected_result == result
        dbsession.refresh(commit)
        assert commit.message == "dsidsahdsahdsa"

    @pytest.mark.django_db
    def test_upload_finisher_task_call_different_branch(
        self, mocker, mock_configuration, dbsession, mock_storage, mock_repo_provider
    ):
        mocker.patch("tasks.upload_finisher.load_intermediate_reports", return_value=[])
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        mocked_3 = mocker.patch.object(
            UploadFinisherTask, "app", conf=mocker.MagicMock(task_time_limit=123)
        )
        mock_finish_reports_processing = mocker.patch.object(
            UploadFinisherTask, "finish_reports_processing"
        )
        mock_finish_reports_processing.return_value = {"notifications_called": True}
        mocked_3.send_task.return_value = True

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
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}],
            "parallel_incremental_result": {"upload_pk": 0},
        }
        result = UploadFinisherTask().run_impl(
            dbsession,
            [previous_results],
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
        )
        expected_result = {"notifications_called": True}
        assert expected_result == result
        dbsession.refresh(commit)
        assert commit.message == "dsidsahdsahdsa"

    def test_should_call_notifications(self, dbsession):
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

        assert (
            UploadFinisherTask().should_call_notifications(
                commit,
                commit_yaml,
                [{"arguments": {"url": "url"}, "successful": True}],
                None,
            )
            == ShouldCallNotifyResult.NOTIFY
        )

    def test_should_call_notifications_local_upload(self, dbsession):
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

        assert (
            UploadFinisherTask().should_call_notifications(
                commit, commit_yaml, [], "local_report1"
            )
            == ShouldCallNotifyResult.DO_NOT_NOTIFY
        )

    def test_should_call_notifications_manual_trigger(self, dbsession):
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

        assert (
            UploadFinisherTask().should_call_notifications(
                commit, commit_yaml, [], None
            )
            == ShouldCallNotifyResult.DO_NOT_NOTIFY
        )

    def test_should_call_notifications_manual_trigger_off(self, dbsession):
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

        assert (
            UploadFinisherTask().should_call_notifications(
                commit,
                commit_yaml,
                [{"arguments": {"url": "url"}, "successful": True}],
                None,
            )
            == ShouldCallNotifyResult.NOTIFY
        )

    @pytest.mark.parametrize(
        "notify_error,result",
        [
            (True, ShouldCallNotifyResult.NOTIFY_ERROR),
            (False, ShouldCallNotifyResult.DO_NOT_NOTIFY),
        ],
    )
    def test_should_call_notifications_no_successful_reports(
        self, dbsession, notify_error, result
    ):
        commit_yaml = {
            "codecov": {
                "max_report_age": "1y ago",
                "notify": {"notify_error": notify_error},
            }
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

        assert (
            UploadFinisherTask().should_call_notifications(
                commit,
                commit_yaml,
                12 * [{"arguments": {"url": "url"}, "successful": False}],
                None,
            )
            == result
        )

    def test_should_call_notifications_not_enough_builds(self, dbsession, mocker):
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

        assert (
            UploadFinisherTask().should_call_notifications(
                commit,
                commit_yaml,
                9 * [{"arguments": {"url": "url"}, "successful": True}],
                None,
            )
            == ShouldCallNotifyResult.DO_NOT_NOTIFY
        )

    def test_should_call_notifications_more_than_enough_builds(self, dbsession, mocker):
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

        assert (
            UploadFinisherTask().should_call_notifications(
                commit,
                commit_yaml,
                2 * [{"arguments": {"url": "url"}, "successful": True}],
                None,
            )
            == ShouldCallNotifyResult.NOTIFY
        )

    def test_finish_reports_processing(self, dbsession, mocker):
        commit_yaml = {}
        mocked_app = mocker.patch.object(UploadFinisherTask, "app")
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        res = UploadFinisherTask().finish_reports_processing(
            dbsession,
            commit,
            UserYaml(commit_yaml),
            [{"successful": True}],
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

    def test_finish_reports_processing_with_pull(self, dbsession, mocker):
        commit_yaml = {}
        mocked_app = mocker.patch.object(
            UploadFinisherTask,
            "app",
            tasks={
                "app.tasks.notify.Notify": mocker.MagicMock(),
                "app.tasks.pulls.Sync": mocker.MagicMock(),
                "app.tasks.compute_comparison.ComputeComparison": mocker.MagicMock(),
                "app.tasks.upload.UploadCleanLabelsIndex": mocker.MagicMock(),
            },
        )
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            owner__username="ThiagoCodecov",
            yaml=commit_yaml,
        )
        pull = PullFactory.create(repository=repository)

        dbsession.add(repository)
        dbsession.add(pull)
        dbsession.flush()

        compared_to = CommitFactory.create(repository=repository)
        pull.compared_to = compared_to.commitid
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository=repository,
            pullid=pull.pullid,
        )
        dbsession.add(commit)
        dbsession.add(compared_to)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        res = UploadFinisherTask().finish_reports_processing(
            dbsession,
            commit,
            UserYaml(commit_yaml),
            [{"successful": True}],
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
        mocked_app.tasks[
            "app.tasks.upload.UploadCleanLabelsIndex"
        ].apply_async.assert_not_called()

    def test_finish_reports_processing_call_clean_labels(self, dbsession, mocker):
        commit_yaml = {
            "flag_management": {
                "individual_flags": [
                    {
                        "name": "smart-tests",
                        "carryforward": True,
                        "carryforward_mode": "labels",
                    },
                    {
                        "name": "just-tests",
                        "carryforward": True,
                    },
                ]
            }
        }
        mocked_app = mocker.patch.object(UploadFinisherTask, "app")
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        res = UploadFinisherTask().finish_reports_processing(
            dbsession,
            commit,
            UserYaml(commit_yaml),
            [{"successful": True, "arguments": {"flags": "smart-tests"}}],
            None,
            checkpoints,
        )
        assert res == {"notifications_called": True}
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_any_call(
            kwargs={
                "commitid": commit.commitid,
                "current_yaml": commit_yaml,
                "repoid": commit.repoid,
                _kwargs_key(UploadFlow): ANY,
            },
        )
        mocked_app.tasks[
            "app.tasks.upload.UploadCleanLabelsIndex"
        ].apply_async.assert_called_with(
            kwargs={
                "repoid": commit.repoid,
                "commitid": commit.commitid,
                "report_code": None,
            },
        )
        assert mocked_app.send_task.call_count == 0

    @pytest.mark.parametrize(
        "notify_error",
        [True, False],
    )
    def test_finish_reports_processing_no_notification(
        self, dbsession, mocker, notify_error
    ):
        commit_yaml = {"codecov": {"notify": {"notify_error": notify_error}}}
        mocked_app = mocker.patch.object(
            UploadFinisherTask,
            "app",
            tasks={
                "app.tasks.notify.NotifyErrorTask": mocker.MagicMock(),
                "app.tasks.notify.Notify": mocker.MagicMock(),
            },
        )
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
        )
        dbsession.add(commit)
        dbsession.flush()

        checkpoints = _create_checkpoint_logger(mocker)
        res = UploadFinisherTask().finish_reports_processing(
            dbsession,
            commit,
            UserYaml(commit_yaml),
            [{"successful": False}],
            None,
            checkpoints,
        )
        assert res == {"notifications_called": False}
        if notify_error:
            assert mocked_app.send_task.call_count == 0
            mocked_app.tasks[
                "app.tasks.notify.NotifyErrorTask"
            ].apply_async.assert_called_once()
            mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_not_called()
        else:
            assert mocked_app.send_task.call_count == 0
            mocked_app.tasks[
                "app.tasks.notify.NotifyErrorTask"
            ].apply_async.assert_not_called()
            mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_not_called()

    @pytest.mark.django_db
    def test_upload_finisher_task_calls_save_commit_measurements_task(
        self, mocker, dbsession, mock_storage, mock_repo_provider
    ):
        mocker.patch("tasks.upload_finisher.load_intermediate_reports", return_value=[])
        mocked_app = mocker.patch.object(
            UploadFinisherTask,
            "app",
            tasks={
                timeseries_save_commit_measurements_task_name: mocker.MagicMock(),
                "app.tasks.notify.Notify": mocker.MagicMock(),
            },
            conf=mocker.MagicMock(task_time_limit=123),
        )

        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()

        previous_results = {
            "processings_so_far": [{"arguments": {}, "successful": True}],
            "parallel_incremental_result": {"upload_pk": 0},
        }
        UploadFinisherTask().run_impl(
            dbsession,
            [previous_results],
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
        )

        mocked_app.tasks[
            timeseries_save_commit_measurements_task_name
        ].apply_async.assert_called_once_with(
            kwargs={
                "commitid": commit.commitid,
                "repoid": commit.repoid,
                "dataset_names": None,
            }
        )

    @pytest.mark.django_db()
    def test_retry_on_report_lock(self, dbsession, mock_redis):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()

        mock_redis.lock.side_effect = LockError()

        task = UploadFinisherTask()
        task.request.retries = 0

        with pytest.raises(Retry):
            task.run_impl(
                dbsession,
                [
                    {
                        "processings_so_far": [{"successful": True, "arguments": {}}],
                        "parallel_incremental_result": {"upload_pk": 1},
                    }
                ],
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                run_fully_parallel=True,
            )


class TestShouldCleanLabelsIndex(object):
    @pytest.mark.parametrize(
        "processing_results, expected",
        [
            (
                [{"successful": True, "arguments": {"flags": "smart-tests"}}],
                True,
            ),
            (
                [{"successful": True, "arguments": {"flags": "just-tests"}}],
                False,
            ),
            (
                [
                    {
                        "successful": True,
                        "arguments": {"flags": "just-tests,smart-tests"},
                    }
                ],
                True,
            ),
            (
                [{"successful": False, "arguments": {"flags": "smart-tests"}}],
                False,
            ),
            (
                [
                    {"successful": True, "arguments": {"flags": "just-tests"}},
                    {"successful": True, "arguments": {"flags": "smart-tests"}},
                ],
                True,
            ),
        ],
    )
    def test_should_clean_labels_index(self, processing_results, expected):
        commit_yaml = UserYaml(
            {
                "flag_management": {
                    "individual_flags": [
                        {
                            "name": "smart-tests",
                            "carryforward": True,
                            "carryforward_mode": "labels",
                        },
                        {
                            "name": "just-tests",
                            "carryforward": True,
                        },
                    ]
                }
            }
        )
        task = UploadFinisherTask()
        result = task.should_clean_labels_index(commit_yaml, processing_results)
        assert result == expected
