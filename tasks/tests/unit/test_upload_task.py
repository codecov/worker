import json
from pathlib import Path
from datetime import datetime
from celery.exceptions import Retry

import pytest
import mock
from redis.exceptions import LockError
from shared.torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError

from tasks.upload import UploadTask
from tasks.upload_processor import upload_processor_task
from tasks.upload_finisher import upload_finisher_task
from database.tests.factories import CommitFactory, OwnerFactory, RepositoryFactory
from database.models import Upload
from helpers.exceptions import RepositoryWithoutValidBotError
from services.archive import ArchiveService
from services.report import ReportService, NotReadyToBuildReportYetError

here = Path(__file__)


class FakeRedis(object):
    """
        This is a fake, very rudimentary redis implementation to ease the managing
         of mocking `exists`, `lpop` and whatnot in the context of Upload jobs
    """

    def __init__(self, mocker):
        self.lists = {}
        self.keys = {}
        self.lock = mocker.MagicMock()
        self.delete = mocker.MagicMock()
        self.sismember = mocker.MagicMock()
        self.hdel = mocker.MagicMock()

    def exists(self, key):
        if self.lists.get(key):
            return True
        if self.keys.get(key) is not None:
            return True
        return False

    def get(self, key):
        if self.keys.get(key) is not None:
            return self.keys.get(key)
        if self.lists.get(key):
            return self.lists.get(key)

    def lpop(self, key):
        res = self.lists.get(key).pop(0)
        if self.lists.get(key) == []:
            del self.lists[key]
        return res

    def delete(self, key):
        del self.lists[key]


@pytest.fixture
def mock_redis(mocker):
    m = mocker.patch("services.redis._get_redis_instance_from_url")
    redis_server = FakeRedis(mocker)
    m.return_value = redis_server
    yield redis_server


@pytest.mark.integration
class TestUploadTaskIntegration(object):
    @pytest.mark.asyncio
    async def test_upload_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch("tasks.upload.chain")
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        redis_queue = [{"url": url, "build": "some_random_build"}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadTask, "app")
        mocked_3.send_task.return_value = True

        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="ThiagoCodecov",
            repository__owner__service="github",
            repository__yaml={"codecov": {"max_report_age": "1y ago"}},
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lists[
            f"testuploads/{commit.repoid}/{commit.commitid}"
        ] = jsonified_redis_queue
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_setup": False, "was_updated": True}
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        assert commit.parent_commit_id is None
        assert commit.report is not None
        assert commit.report.details is not None
        sessions = commit.report.uploads
        assert len(sessions) == 1
        first_session = (
            dbsession.query(Upload)
            .filter_by(report_id=commit.report.id, build_code="some_random_build")
            .first()
        )
        t1 = upload_processor_task.signature(
            args=({},),
            kwargs=dict(
                repoid=commit.repoid,
                commitid="abf6d4df662c47e32460020ab14abf9303581429",
                commit_yaml={"codecov": {"max_report_age": "1y ago"}},
                arguments_list=[
                    {
                        "url": url,
                        "build": "some_random_build",
                        "upload_pk": first_session.id,
                    }
                ],
            ),
        )
        t2 = upload_finisher_task.signature(
            kwargs=dict(
                repoid=commit.repoid,
                commitid="abf6d4df662c47e32460020ab14abf9303581429",
                commit_yaml={"codecov": {"max_report_age": "1y ago"}},
            ),
        )
        mocked_1.assert_called_with(t1, t2)

    @pytest.mark.asyncio
    async def test_upload_task_call_no_jobs(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        mocked_3 = mocker.patch.object(UploadTask, "app")
        mocked_3.send_task.return_value = True

        commit = CommitFactory.create(
            parent_commit_id=None,
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={"codecov": {"max_report_age": "1y ago"}},
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lists[f"testuploads/{commit.repoid}/{commit.commitid}"] = []
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {
            "was_setup": False,
            "was_updated": False,
            "tasks_were_scheduled": False,
        }
        assert expected_result == result
        assert commit.message == ""
        assert commit.parent_commit_id is None

    @pytest.mark.asyncio
    async def test_upload_task_call_multiple_processors(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch("tasks.upload.chain")
        redis_queue = [
            {"build": "part1"},
            {"build": "part2"},
            {"build": "part3"},
            {"build": "part4"},
            {"build": "part5"},
            {"build": "part6"},
            {"build": "part7"},
            {"build": "part8"},
        ]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mocked_3 = mocker.patch.object(UploadTask, "app")
        mocked_3.send_task.return_value = True

        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="ThiagoCodecov",
            repository__owner__service="github",
            repository__yaml={"codecov": {"max_report_age": "1y ago"}},
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lists[
            f"testuploads/{commit.repoid}/{commit.commitid}"
        ] = jsonified_redis_queue
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_setup": False, "was_updated": True}
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        assert commit.parent_commit_id is None
        t1 = upload_processor_task.signature(
            args=({},),
            kwargs=dict(
                repoid=commit.repoid,
                commitid="abf6d4df662c47e32460020ab14abf9303581429",
                commit_yaml={"codecov": {"max_report_age": "1y ago"}},
                arguments_list=[
                    {"build": "part1", "upload_pk": mocker.ANY},
                    {"build": "part2", "upload_pk": mocker.ANY},
                    {"build": "part3", "upload_pk": mocker.ANY},
                ],
            ),
        )
        t2 = upload_processor_task.signature(
            args=(),
            kwargs=dict(
                repoid=commit.repoid,
                commitid="abf6d4df662c47e32460020ab14abf9303581429",
                commit_yaml={"codecov": {"max_report_age": "1y ago"}},
                arguments_list=[
                    {"build": "part4", "upload_pk": mocker.ANY},
                    {"build": "part5", "upload_pk": mocker.ANY},
                    {"build": "part6", "upload_pk": mocker.ANY},
                ],
            ),
        )
        t3 = upload_processor_task.signature(
            args=(),
            kwargs=dict(
                repoid=commit.repoid,
                commitid="abf6d4df662c47e32460020ab14abf9303581429",
                commit_yaml={"codecov": {"max_report_age": "1y ago"}},
                arguments_list=[
                    {"build": "part7", "upload_pk": mocker.ANY},
                    {"build": "part8", "upload_pk": mocker.ANY},
                ],
            ),
        )
        t_final = upload_finisher_task.signature(
            kwargs=dict(
                repoid=commit.repoid,
                commitid="abf6d4df662c47e32460020ab14abf9303581429",
                commit_yaml={"codecov": {"max_report_age": "1y ago"}},
            ),
        )
        mocked_1.assert_called_with(t1, t2, t3, t_final)
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        mock_redis.lock.assert_any_call(
            f"upload_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.asyncio
    async def test_upload_task_proper_parent(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch("tasks.upload.chain")
        mocked_3 = mocker.patch.object(UploadTask, "app")
        mocked_3 = mocker.patch.object(
            UploadTask, "lists_of_arguments", return_value=[]
        )
        mocked_3.send_task.return_value = True

        owner = OwnerFactory.create(
            service="github",
            username="ThiagoCodecov",
            unencrypted_oauth_token="test76zow6xgh7modd88noxr245j2z25t4ustoff",
        )
        dbsession.add(owner)

        repo = RepositoryFactory.create(
            owner=owner,
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
        )
        dbsession.add(repo)

        parent_commit = CommitFactory.create(
            message="",
            commitid="c5b67303452bbff57cc1f49984339cde39eb1db5",
            repository=repo,
        )

        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository=repo,
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        redis_queue = [{"build": "part1"}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mock_redis.lists[
            f"testuploads/{commit.repoid}/{commit.commitid}"
        ] = jsonified_redis_queue
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_setup": False, "was_updated": True}
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        assert commit.parent_commit_id == "c5b67303452bbff57cc1f49984339cde39eb1db5"
        assert not mocked_1.called
        mock_redis.lock.assert_any_call(
            f"upload_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.asyncio
    async def test_upload_task_no_bot(
        self, mocker, mock_configuration, dbsession, mock_redis, mock_storage
    ):
        mocked_1 = mocker.patch.object(UploadTask, "schedule_task")
        mocked_3 = mocker.patch.object(UploadTask, "app")
        mocked_3.send_task.return_value = True
        mocked_fetch_yaml = mocker.patch.object(
            UploadTask, "fetch_commit_yaml_and_possibly_store"
        )
        redis_queue = [{"build": "part1"}, {"build": "part2"}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mock_get_repo_service = mocker.patch("tasks.upload.get_repo_provider_service")
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        commit = CommitFactory.create(
            message="",
            parent_commit_id=None,
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lists[
            f"testuploads/{commit.repoid}/{commit.commitid}"
        ] = jsonified_redis_queue
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_setup": False, "was_updated": False}
        assert expected_result == result
        assert commit.message == ""
        assert commit.parent_commit_id is None
        mocked_1.assert_called_with(
            commit,
            {"codecov": {"max_report_age": "764y ago"}},
            [
                {"build": "part1", "upload_pk": mocker.ANY},
                {"build": "part2", "upload_pk": mocker.ANY},
            ],
        )
        assert not mocked_fetch_yaml.called

    @pytest.mark.asyncio
    async def test_upload_task_bot_no_permissions(
        self, mocker, mock_configuration, dbsession, mock_redis, mock_storage
    ):
        mocked_1 = mocker.patch.object(UploadTask, "schedule_task")
        mocked_3 = mocker.patch.object(UploadTask, "app")
        mocked_3.send_task.return_value = True
        mocked_fetch_yaml = mocker.patch.object(
            UploadTask, "fetch_commit_yaml_and_possibly_store"
        )
        redis_queue = [{"build": "part1"}, {"build": "part2"}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mock_get_repo_service = mocker.patch("tasks.upload.get_repo_provider_service")
        mock_get_repo_service.side_effect = TorngitRepoNotFoundError(
            "fake_response", "message"
        )
        commit = CommitFactory.create(
            message="",
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lists[
            f"testuploads/{commit.repoid}/{commit.commitid}"
        ] = jsonified_redis_queue
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {"was_setup": False, "was_updated": False}
        assert expected_result == result
        assert commit.message == ""
        assert commit.parent_commit_id is None
        mocked_1.assert_called_with(
            commit,
            {"codecov": {"max_report_age": "764y ago"}},
            [
                {"build": "part1", "upload_pk": mocker.ANY},
                {"build": "part2", "upload_pk": mocker.ANY},
            ],
        )
        assert not mocked_fetch_yaml.called

    @pytest.mark.asyncio
    async def test_upload_task_bot_unauthorized(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
        mock_repo_provider,
        mock_storage,
    ):
        mocked_schedule_task = mocker.patch.object(UploadTask, "schedule_task")
        mock_app = mocker.patch.object(UploadTask, "app")
        mock_app.send_task.return_value = True
        redis_queue = [{"build": "part1"}, {"build": "part2"}]
        jsonified_redis_queue = [json.dumps(x) for x in redis_queue]
        mock_repo_provider.get_commit.side_effect = TorngitClientError(
            401, "response", "message"
        )
        mock_repo_provider.list_top_level_files.side_effect = TorngitClientError(
            401, "response", "message"
        )
        commit = CommitFactory.create(
            message="",
            parent_commit_id=None,
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={"codecov": {"max_report_age": "764y ago"}},
        )
        mock_repo_provider.data = dict(repo=dict(repoid=commit.repoid))
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lists[
            f"testuploads/{commit.repoid}/{commit.commitid}"
        ] = jsonified_redis_queue
        result = await UploadTask().run_async_within_lock(
            dbsession, mock_redis, commit.repoid, commit.commitid
        )
        assert {"was_setup": False, "was_updated": False} == result
        assert commit.message == ""
        assert commit.parent_commit_id is None
        assert commit.report is not None
        assert commit.report.details is not None
        sessions = commit.report.uploads
        assert len(sessions) == 2
        first_session = (
            dbsession.query(Upload)
            .filter_by(report_id=commit.report.id, build_code="part1")
            .first()
        )
        second_session = (
            dbsession.query(Upload)
            .filter_by(report_id=commit.report.id, build_code="part2")
            .first()
        )
        mocked_schedule_task.assert_called_with(
            commit,
            {"codecov": {"max_report_age": "764y ago"}},
            [
                {"build": "part1", "upload_pk": first_session.id},
                {"build": "part2", "upload_pk": second_session.id},
            ],
        )


class TestUploadTaskUnit(object):
    def test_list_of_arguments(self, mock_redis):
        task = UploadTask()
        first_redis_queue = [
            {"url": "http://example.first.com"},
            {"and_another": "one"},
        ]
        second_redis_queue = [{"args": "an_arg!"}]
        mock_redis.lists["testuploads/542/commitid"] = [
            json.dumps(x) for x in first_redis_queue
        ]
        mock_redis.lists["uploads/542/commitid"] = [
            json.dumps(x) for x in second_redis_queue
        ]
        res = list(task.lists_of_arguments(mock_redis, 542, "commitid"))
        assert res == [
            {"url": "http://example.first.com"},
            {"and_another": "one"},
            {"args": "an_arg!"},
        ]

    def test_normalize_upload_arguments_no_changes(
        self, dbsession, mock_redis, mock_storage
    ):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        reportid = "5fbeee8b-5a41-4925-b59d-470b9d171235"
        arguments_with_redis_key = {"reportid": reportid, "random": "argument"}
        result = UploadTask().normalize_upload_arguments(
            commit, arguments_with_redis_key, mock_redis
        )
        expected_result = {
            "reportid": "5fbeee8b-5a41-4925-b59d-470b9d171235",
            "random": "argument",
        }
        assert expected_result == result

    def test_normalize_upload_arguments_token_removal(
        self, dbsession, mock_redis, mock_storage
    ):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        reportid = "5fbeee8b-5a41-4925-b59d-470b9d171235"
        previous_arguments = {"reportid": reportid, "token": "value"}
        result = UploadTask().normalize_upload_arguments(
            commit, previous_arguments, mock_redis
        )
        expected_result = {
            "reportid": "5fbeee8b-5a41-4925-b59d-470b9d171235",
        }
        assert expected_result == result

    def test_normalize_upload_arguments(
        self, dbsession, mock_redis, mock_storage, mocker
    ):
        mocked_now = mocker.patch.object(ArchiveService, "get_now")
        mocked_now.return_value = datetime(2019, 12, 3)
        mock_redis.keys["commit_chunks.something"] = b"Some weird value"
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        repo_hash = ArchiveService.get_archive_hash(commit.repository)
        reportid = "5fbeee8b-5a41-4925-b59d-470b9d171235"
        arguments_with_redis_key = {
            "redis_key": "commit_chunks.something",
            "reportid": reportid,
            "random": "argument",
        }
        result = UploadTask().normalize_upload_arguments(
            commit, arguments_with_redis_key, mock_redis
        )
        expected_result = {
            "url": f"v4/raw/2019-12-03/{repo_hash}/{commit.commitid}/{reportid}.txt",
            "reportid": "5fbeee8b-5a41-4925-b59d-470b9d171235",
            "random": "argument",
        }
        assert expected_result == result
        assert "archive" in mock_storage.storage
        assert (
            f"v4/raw/2019-12-03/{repo_hash}/{commit.commitid}/{reportid}.txt"
            in mock_storage.storage["archive"]
        )
        content = mock_storage.storage["archive"][
            f"v4/raw/2019-12-03/{repo_hash}/{commit.commitid}/{reportid}.txt"
        ]
        assert b"Some weird value" == content

    def test_schedule_task_with_no_tasks(self, dbsession):
        commit = CommitFactory.create()
        commit_yaml = {}
        argument_list = []
        dbsession.add(commit)
        dbsession.flush()
        result = UploadTask().schedule_task(commit, commit_yaml, argument_list)
        assert result is None

    def test_schedule_task_with_one_task(self, dbsession, mocker):
        mocked_chain = mocker.patch("tasks.upload.chain")
        commit = CommitFactory.create()
        commit_yaml = {"codecov": {"max_report_age": "100y ago"}}
        argument_dict = {"argument_dict": 1}
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
                arguments_list=argument_list,
            ),
        )
        t2 = upload_finisher_task.signature(
            kwargs=dict(
                repoid=commit.repoid, commitid=commit.commitid, commit_yaml=commit_yaml
            ),
        )
        mocked_chain.assert_called_with(t1, t2)

    @pytest.mark.asyncio
    async def test_run_async_unobtainable_lock_no_pending_jobs(
        self, dbsession, mocker, mock_redis
    ):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lock.side_effect = LockError()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        assert result == {
            "tasks_were_scheduled": False,
            "was_setup": False,
            "was_updated": False,
        }

    @pytest.mark.asyncio
    async def test_run_async_unobtainable_lock_too_many_retries(
        self, dbsession, mocker, mock_redis
    ):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lock.side_effect = LockError()
        mock_redis.keys[f"testuploads/{commit.repoid}/{commit.commitid}"] = [
            "something"
        ]
        task = UploadTask()
        task.request.retries = 3
        result = await task.run_async(dbsession, commit.repoid, commit.commitid)
        assert result == {
            "tasks_were_scheduled": False,
            "was_setup": False,
            "was_updated": False,
            "reason": "too_many_retries",
        }

    @pytest.mark.asyncio
    async def test_run_async_currently_processing(self, dbsession, mocker, mock_redis):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        mocked_is_currently_processing = mocker.patch.object(
            UploadTask, "is_currently_processing", return_value=True
        )
        mocked_run_async_within_lock = mocker.patch.object(
            UploadTask, "run_async_within_lock", return_value=True
        )
        task = UploadTask()
        task.request.retries = 0
        with pytest.raises(Retry):
            await task.run_async(dbsession, commit.repoid, commit.commitid)
        mocked_is_currently_processing.assert_called_with(
            mock_redis, commit.repoid, commit.commitid
        )
        assert not mocked_run_async_within_lock.called

    @pytest.mark.asyncio
    async def test_run_async_currently_processing_second_retry(
        self, dbsession, mocker, mock_redis
    ):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        mocked_is_currently_processing = mocker.patch.object(
            UploadTask, "is_currently_processing", return_value=True
        )
        mocked_run_async_within_lock = mocker.patch.object(
            UploadTask, "run_async_within_lock", return_value={"some": "value"}
        )
        task = UploadTask()
        task.request.retries = 1
        result = await task.run_async(dbsession, commit.repoid, commit.commitid)
        mocked_is_currently_processing.assert_called_with(
            mock_redis, commit.repoid, commit.commitid
        )
        assert mocked_run_async_within_lock.called
        assert result == {"some": "value"}

    def test_is_currently_processing(self, mock_redis):
        repoid = 1
        commitid = "adsdadsadfdsjnskgiejrw"
        lock_name = f"upload_processing_lock_{repoid}_{commitid}"
        mock_redis.keys[lock_name] = "val"
        task = UploadTask()
        assert task.is_currently_processing(mock_redis, repoid, commitid)
        assert not task.is_currently_processing(mock_redis, repoid, "pol")

    @pytest.mark.asyncio
    async def test_run_async_unobtainable_lock_retry(
        self, dbsession, mocker, mock_redis
    ):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lock.side_effect = LockError()
        mock_redis.keys[f"testuploads/{commit.repoid}/{commit.commitid}"] = [
            "something"
        ]
        task = UploadTask()
        task.request.retries = 0
        with pytest.raises(Retry):
            await task.run_async(dbsession, commit.repoid, commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_only_commit_yaml(
        self, dbsession, mocker, mock_configuration
    ):
        commit = CommitFactory.create()
        get_source_result = {
            "content": "\n".join(
                ["codecov:", "  notify:", "    require_ci_to_pass: yes",]
            )
        }
        list_top_level_files_result = [
            {"name": ".gitignore", "path": ".gitignore", "type": "file"},
            {"name": ".travis.yml", "path": ".travis.yml", "type": "file"},
            {"name": "README.rst", "path": "README.rst", "type": "file"},
            {"name": "awesome", "path": "awesome", "type": "folder"},
            {"name": "codecov", "path": "codecov", "type": "file"},
            {"name": "codecov.yaml", "path": "codecov.yaml", "type": "file"},
            {"name": "tests", "path": "tests", "type": "folder"},
        ]
        repository_service = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(
                return_value=list_top_level_files_result
            ),
            get_source=mock.AsyncMock(return_value=get_source_result),
        )

        result = await UploadTask().fetch_commit_yaml_and_possibly_store(
            commit, repository_service
        )
        expected_result = {"codecov": {"notify": {}, "require_ci_to_pass": True}}
        assert result == expected_result
        repository_service.get_source.assert_called_with(
            "codecov.yaml", commit.commitid
        )
        repository_service.list_top_level_files.assert_called_with(commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_and_base_yaml(
        self, dbsession, mock_configuration, mocker
    ):
        mock_configuration.set_params({"site": {"coverage": {"precision": 14}}})
        commit = CommitFactory.create()
        get_source_result = {
            "content": "\n".join(
                ["codecov:", "  notify:", "    require_ci_to_pass: yes",]
            )
        }
        list_top_level_files_result = [
            {"name": ".travis.yml", "path": ".travis.yml", "type": "file"},
            {"name": "awesome", "path": "awesome", "type": "folder"},
            {"name": ".codecov.yaml", "path": ".codecov.yaml", "type": "file"},
        ]
        repository_service = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(
                return_value=list_top_level_files_result
            ),
            get_source=mock.AsyncMock(return_value=get_source_result),
        )

        result = await UploadTask().fetch_commit_yaml_and_possibly_store(
            commit, repository_service
        )
        expected_result = {
            "codecov": {"notify": {}, "require_ci_to_pass": True},
            "coverage": {"precision": 14},
        }
        assert result == expected_result
        repository_service.get_source.assert_called_with(
            ".codecov.yaml", commit.commitid
        )
        repository_service.list_top_level_files.assert_called_with(commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_and_repo_yaml(
        self, dbsession, mock_configuration, mocker
    ):
        mock_configuration.set_params({"site": {"coverage": {"precision": 14}}})
        commit = CommitFactory.create(
            repository__yaml={"codecov": {"max_report_age": "1y ago"}},
            repository__branch="supeduperbranch",
            branch="supeduperbranch",
        )
        get_source_result = {
            "content": "\n".join(
                ["codecov:", "  notify:", "    require_ci_to_pass: yes",]
            )
        }
        list_top_level_files_result = [
            {"name": ".gitignore", "path": ".gitignore", "type": "file"},
            {"name": ".codecov.yaml", "path": ".codecov.yaml", "type": "file"},
            {"name": "tests", "path": "tests", "type": "folder"},
        ]
        repository_service = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(
                return_value=list_top_level_files_result
            ),
            get_source=mock.AsyncMock(return_value=get_source_result),
        )

        result = await UploadTask().fetch_commit_yaml_and_possibly_store(
            commit, repository_service
        )
        expected_result = {
            "codecov": {"notify": {}, "require_ci_to_pass": True},
            "coverage": {"precision": 14},
        }
        assert result == expected_result
        assert commit.repository.yaml == {
            "codecov": {"notify": {}, "require_ci_to_pass": True}
        }
        repository_service.get_source.assert_called_with(
            ".codecov.yaml", commit.commitid
        )
        repository_service.list_top_level_files.assert_called_with(commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_no_commit_yaml(
        self, dbsession, mock_configuration, mocker
    ):
        mock_configuration.set_params({"site": {"coverage": {"round": "up"}}})
        commit = CommitFactory.create(
            repository__owner__yaml={"coverage": {"precision": 2}},
            repository__yaml={"codecov": {"max_report_age": "1y ago"}},
            repository__branch="supeduperbranch",
            branch="supeduperbranch",
        )
        repository_service = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(
                side_effect=TorngitClientError(404, "fake_response", "message")
            )
        )

        result = await UploadTask().fetch_commit_yaml_and_possibly_store(
            commit, repository_service
        )
        expected_result = {
            "coverage": {"precision": 2, "round": "up"},
            "codecov": {"max_report_age": "1y ago"},
        }
        assert result == expected_result
        assert commit.repository.yaml == {"codecov": {"max_report_age": "1y ago"}}

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_and_possibly_store_commit_yaml_invalid_commit_yaml(
        self, dbsession, mock_configuration, mocker
    ):
        mock_configuration.set_params({"site": {"comment": {"behavior": "new"}}})
        commit = CommitFactory.create(
            repository__owner__yaml={"coverage": {"precision": 2}},
            repository__yaml={"codecov": {"max_report_age": "1y ago"}},
            repository__branch="supeduperbranch",
            branch="supeduperbranch",
        )
        get_source_result = {
            "content": "\n".join(
                ["bad_key:", "  notify:", "    require_ci_to_pass: yes",]
            )
        }
        list_top_level_files_result = [
            {"name": ".gitignore", "path": ".gitignore", "type": "file"},
            {"name": ".codecov.yaml", "path": ".codecov.yaml", "type": "file"},
            {"name": "tests", "path": "tests", "type": "folder"},
        ]
        repository_service = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(
                return_value=list_top_level_files_result
            ),
            get_source=mock.AsyncMock(return_value=get_source_result),
        )

        result = await UploadTask().fetch_commit_yaml_and_possibly_store(
            commit, repository_service
        )
        expected_result = {
            "coverage": {"precision": 2},
            "codecov": {"max_report_age": "1y ago"},
            "comment": {"behavior": "new"},
        }
        assert result == expected_result
        assert commit.repository.yaml == {"codecov": {"max_report_age": "1y ago"}}

    @pytest.mark.asyncio
    async def test_possibly_setup_webhooks_public_repo(
        self, mocker, mock_configuration, mock_repo_provider
    ):
        mock_configuration.set_params({"github": {"bot": {"key": "somekey"}}})
        commit = CommitFactory.create(
            repository__private=False,
            repository__owner__unencrypted_oauth_token="aaaaabbbbhhhh",
        )
        task = UploadTask()
        mock_repo_provider.data = mocker.MagicMock()
        mock_repo_provider.service = "github"
        res = await task.possibly_setup_webhooks(commit, mock_repo_provider)
        assert res is True
        mock_repo_provider.post_webhook.assert_called_with(
            "Codecov Webhook. None",
            "None/webhooks/github",
            ["pull_request", "delete", "push", "public", "status", "repository"],
            "ab164bf3f7d947f2a0681b215404873e",
            token=None,
        )

    @pytest.mark.asyncio
    async def test_upload_not_ready_to_build_report(
        self, dbsession, mocker, mock_configuration, mock_repo_provider, mock_redis
    ):
        mock_configuration.set_params({"github": {"bot": {"key": "somekey"}}})
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        mocker.patch.object(UploadTask, "has_pending_jobs", return_value=True)
        task = UploadTask()
        mock_repo_provider.data = mocker.MagicMock()
        mock_repo_provider.service = "github"
        mocker.patch.object(
            ReportService,
            "initialize_and_save_report",
            side_effect=NotReadyToBuildReportYetError(),
        )
        with pytest.raises(Retry):
            await task.run_async_within_lock(
                dbsession, mock_redis, commit.repoid, commit.commitid
            )
