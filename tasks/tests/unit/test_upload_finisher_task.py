import json
from pathlib import Path

import pytest

from shared.yaml import UserYaml
from tasks.upload_finisher import UploadFinisherTask
from database.tests.factories import CommitFactory, RepositoryFactory, PullFactory

here = Path(__file__)


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
        result = await UploadFinisherTask().run_async(
            dbsession,
            previous_results,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
        )
        assert commit.notified is False
        expected_result = {"notifications_called": True}
        assert expected_result == result
        dbsession.refresh(commit)
        assert commit.message == "dsidsahdsahdsa"
        expected_cache = {
            "commit": {
                "author": {
                    "name": commit.author.name,
                    "email": commit.author.email,
                    "service": "github",
                    "username": commit.author.username,
                    "service_id": commit.author.service_id,
                },
                "totals": {
                    "C": 0,
                    "M": 0,
                    "N": 0,
                    "b": 0,
                    "c": "85.00000",
                    "d": 0,
                    "diff": [1, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                    "f": 3,
                    "h": 17,
                    "m": 3,
                    "n": 20,
                    "p": 0,
                    "s": 1,
                },
                "message": commit.message,
                "commitid": commit.commitid,
                "ci_passed": True,
                "timestamp": commit.timestamp.isoformat(),
            }
        }
        assert commit.repository.cache_do_not_use == expected_cache

        mock_redis.lock.assert_called_with(
            f"upload_finisher_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

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
        expected_cache = {
            "commit": {
                "author": None,
                "totals": {
                    "C": 0,
                    "M": 0,
                    "N": 0,
                    "b": 0,
                    "c": "85.00000",
                    "d": 0,
                    "diff": [1, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                    "f": 3,
                    "h": 17,
                    "m": 3,
                    "n": 20,
                    "p": 0,
                    "s": 1,
                },
                "message": commit.message,
                "commitid": commit.commitid,
                "ci_passed": True,
                "timestamp": commit.timestamp.isoformat(),
            }
        }
        assert commit.repository.cache_do_not_use == expected_cache

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
        assert commit.repository.cache_do_not_use is None

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
            commit, commit_yaml, processing_results
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
            commit, commit_yaml, processing_results
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_not_enough_builds(self, dbsession):
        commit_yaml = {"codecov": {"notify": {"after_n_builds": 9}}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
            report_json={
                "sessions": {str(n): {"a": str(f"http://{n}")} for n in range(8)}
            },
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            "processings_so_far": 9
            * [{"arguments": {"url": "url"}, "successful": True}]
        }
        assert not UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results
        )

    @pytest.mark.asyncio
    async def test_should_call_notifications_more_than_enough_builds(self, dbsession):
        commit_yaml = {"codecov": {"notify": {"after_n_builds": 9}}}
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml=commit_yaml,
            report_json={
                "sessions": {str(n): {"a": str(f"http://{n}")} for n in range(10)}
            },
        )
        dbsession.add(commit)
        dbsession.flush()
        processing_results = {
            "processings_so_far": 2
            * [{"arguments": {"url": "url"}, "successful": True}]
        }
        assert UploadFinisherTask().should_call_notifications(
            commit, commit_yaml, processing_results
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
        res = await UploadFinisherTask().finish_reports_processing(
            dbsession, commit, UserYaml(commit_yaml), processing_results
        )
        assert res == {"notifications_called": True}
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_called_with(
            kwargs=dict(
                commitid=commit.commitid, current_yaml=commit_yaml, repoid=commit.repoid
            ),
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
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository=repository,
            pullid=pull.pullid,
        )
        processing_results = {"processings_so_far": [{"successful": True}]}
        dbsession.add(commit)
        dbsession.add(pull)
        dbsession.flush()
        res = await UploadFinisherTask().finish_reports_processing(
            dbsession, commit, UserYaml(commit_yaml), processing_results
        )
        assert res == {"notifications_called": True}
        mocked_app.tasks["app.tasks.notify.Notify"].apply_async.assert_called_with(
            kwargs=dict(
                commitid=commit.commitid, current_yaml=commit_yaml, repoid=commit.repoid
            ),
        )
        mocked_app.tasks["app.tasks.pulls.Sync"].apply_async.assert_called_with(
            kwargs={
                "pullid": pull.pullid,
                "repoid": pull.repoid,
                "should_send_notifications": False,
            }
        )
        assert mocked_app.send_task.call_count == 0

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
        res = await UploadFinisherTask().finish_reports_processing(
            dbsession, commit, UserYaml(commit_yaml), processing_results
        )
        assert res == {"notifications_called": False}
        assert mocked_app.send_task.call_count == 0
        assert not mocked_app.tasks["app.tasks.notify.Notify"].apply_async.called
