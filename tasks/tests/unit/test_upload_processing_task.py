from pathlib import Path

import pytest
import celery
from redis.exceptions import LockError
from shared.torngit.exceptions import TorngitObjectNotFoundError
from shared.reports.resources import Report, ReportFile, ReportLine, ReportTotals
from shared.storage.exceptions import FileNotInStorageError

from tasks.upload_processor import UploadProcessorTask
from database.models import CommitReport, ReportDetails
from database.tests.factories import CommitFactory, UploadFactory
from helpers.exceptions import (
    ReportExpiredException,
    ReportEmptyError,
    RepositoryWithoutValidBotError,
)
from services.archive import ArchiveService
from services.report import ReportService, NotReadyToBuildReportYetError

here = Path(__file__)


class TestUploadProcessorTask(object):
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_processor_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_uploaded_report_1.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        redis_queue = [{"url": url}]
        mocked_3 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_3.send_task.return_value = True

        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__owner__service="github",
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_, files_array=[])
        dbsession.add(report_details)
        dbsession.flush()
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}]
        }
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        expected_generated_report = {
            "files": {
                "awesome/__init__.py": [
                    0,
                    [0, 14, 10, 4, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 14, 10, 4, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                    [0, 4, 4, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                ],
                "tests/__init__.py": [
                    1,
                    [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "tests/test_sample.py": [
                    2,
                    [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "N": None,
                    "a": url,
                    "c": None,
                    "e": None,
                    "f": None,
                    "j": None,
                    "n": None,
                    "p": None,
                    "t": [3, 24, 19, 5, 0, "79.16667", 0, 0, 0, 0, 0, 0, 0],
                    "u": None,
                    "d": commit.report_json["sessions"]["0"]["d"],
                    "st": "uploaded",
                    "se": {},
                }
            },
        }
        assert commit.report_json == expected_generated_report
        mocked_1.assert_called_with(commit.commitid)
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_processing_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.asyncio
    async def test_upload_processor_call_with_upload_obj(
        self, mocker, mock_configuration, dbsession, mock_storage, mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            author__service="github",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__service="github",
            repository__owner__username="ThiagoCodecov",
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_, files_array=[])
        dbsession.add(report_details)
        dbsession.flush()
        upload = UploadFactory.create(report=current_report_row, state="started")
        dbsession.add(upload)
        dbsession.flush()
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_uploaded_report_1.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocked_3 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_3.send_task.return_value = True
        result = await UploadProcessorTask().process_async_within_lock(
            db_session=dbsession,
            redis_connection=mock_redis,
            previous_results={},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [
                {"arguments": {"url": url, "upload_pk": upload.id_}, "successful": True}
            ]
        }
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        assert upload.state == "processed"
        expected_generated_report = {
            "files": {
                "awesome/__init__.py": [
                    0,
                    [0, 14, 10, 4, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 14, 10, 4, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "tests/__init__.py": [
                    1,
                    [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "tests/test_sample.py": [
                    2,
                    [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "N": None,
                    "a": url,
                    "c": None,
                    "e": None,
                    "f": None,
                    "j": None,
                    "n": None,
                    "p": None,
                    "t": [3, 24, 19, 5, 0, "79.16667", 0, 0, 0, 0, 0, 0, 0],
                    "u": None,
                    "d": commit.report_json["sessions"]["0"]["d"],
                    "st": "uploaded",
                    "se": {},
                }
            },
        }
        assert (
            commit.report_json["files"]["awesome/__init__.py"]
            == expected_generated_report["files"]["awesome/__init__.py"]
        )
        assert commit.report_json["files"] == expected_generated_report["files"]
        assert commit.report_json == expected_generated_report
        mocked_1.assert_called_with(commit.commitid)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_task_call_existing_chunks(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        with open(here.parent.parent / "samples" / "sample_chunks_1.txt") as f:
            content = f.read()
            mocked_1.return_value = content
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_uploaded_report_1.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        redis_queue = [{"url": url}]
        mocked_3 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_3.send_task.return_value = True

        commit = CommitFactory.create(
            message="dsidsahdsahdsa",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__owner__service="github",
            repository__name="example-python",
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_, files_array=[])
        dbsession.add(report_details)
        dbsession.flush()
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [{"arguments": {"url": url}, "successful": True}]
        }
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        mocked_1.assert_called_with(commit.commitid)
        # mocked_3.send_task.assert_called_with(
        #     'app.tasks.notify.Notify',
        #     args=None,
        #     kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        # )
        # mock_redis.assert_called_with(None)
        mock_redis.lock.assert_called_with(
            f"upload_processing_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.asyncio
    async def test_upload_task_call_with_try_later(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(
            UploadProcessorTask, "do_process_individual_report"
        )
        mocked_2.side_effect = Exception()
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_3 = mocker.patch.object(UploadProcessorTask, "retry")
        mocked_3.side_effect = celery.exceptions.Retry()
        mocked_4 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        redis_queue = [{"url": "url"}]
        with pytest.raises(celery.exceptions.Retry):
            await UploadProcessorTask().run_async(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=redis_queue,
            )
        mocked_2.assert_called_with(
            mocker.ANY,
            mock_redis,
            commit,
            mocker.ANY,
            False,
            url="url",
            upload_pk=mocker.ANY,
        )
        mocked_3.assert_called_with(countdown=20, max_retries=5)

    @pytest.mark.asyncio
    async def test_upload_task_call_with_redis_lock_unobtainable(
        self, mocker, mock_configuration, dbsession, mock_redis
    ):
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_3 = mocker.patch.object(UploadProcessorTask, "retry")
        mocked_3.side_effect = celery.exceptions.Retry()
        mocked_4 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_4.send_task.return_value = True
        mock_redis.lock.return_value.__enter__.side_effect = LockError()
        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        mocked_random = mocker.patch("random.randint", return_value=179)
        with pytest.raises(celery.exceptions.Retry):
            await UploadProcessorTask().run_async(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=[{"url": "url"}],
            )
        mocked_3.assert_called_with(countdown=179, max_retries=5)
        mocked_random.assert_called_with(100, 200)

    @pytest.mark.asyncio
    async def test_upload_processing_task_call_with_not_ready_report(
        self, mocker, mock_configuration, dbsession, mock_redis, mock_storage
    ):
        mocker.patch.object(
            ReportService,
            "build_report_from_commit",
            side_effect=NotReadyToBuildReportYetError(),
        )
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        with pytest.raises(celery.exceptions.Retry):
            await UploadProcessorTask().run_async(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=[{"url": "url"}],
            )

    @pytest.mark.asyncio
    async def test_upload_task_call_with_expired_report(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(
            UploadProcessorTask, "do_process_individual_report"
        )
        false_report = mocker.MagicMock(
            to_database=mocker.MagicMock(return_value=({}, "{}")), totals=ReportTotals()
        )
        mocked_2.side_effect = [
            (false_report, mocker.MagicMock(id=1, totals=ReportTotals())),
            ReportExpiredException(),
        ]
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_4 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_, files_array=[])
        dbsession.add(report_details)
        dbsession.flush()
        redis_queue = [
            {"url": "url", "what": "huh"},
            {"url": "url2", "extra_param": 45},
        ]
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [
                {"arguments": {"url": "url", "what": "huh"}, "successful": True},
                {
                    "arguments": {"extra_param": 45, "url": "url2"},
                    "error_type": "report_expired",
                    "report": None,
                    "should_retry": False,
                    "successful": False,
                },
            ]
        }
        assert expected_result == result
        assert commit.state == "complete"

    @pytest.mark.asyncio
    async def test_upload_task_process_individual_report_with_notfound_report(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(
            UploadProcessorTask, "do_process_individual_report"
        )
        false_report = mocker.MagicMock(
            to_database=mocker.MagicMock(return_value=({}, "{}")), totals=ReportTotals()
        )
        mocked_2.side_effect = FileNotInStorageError()
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_4 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={"codecov": {"max_report_age": False}},
        )
        dbsession.add(commit)
        dbsession.flush()
        upload = UploadFactory.create(report__commit=commit)
        dbsession.add(upload)
        arguments = {"url": "url2", "extra_param": 45}
        task = UploadProcessorTask()
        task.request.retries = 1
        result = task.process_individual_report(
            report_service=ReportService({"codecov": {"max_report_age": False}}),
            redis_connection=mock_redis,
            commit=commit,
            report=false_report,
            upload_obj=upload,
            **arguments,
        )
        expected_result = {
            "error_type": "file_not_in_storage",
            "report": None,
            "should_retry": False,
            "successful": False,
        }
        assert expected_result == result
        assert commit.state == "complete"
        assert upload.state == "error"

    @pytest.mark.asyncio
    async def test_upload_task_call_with_empty_report(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(
            UploadProcessorTask, "do_process_individual_report"
        )
        false_report = mocker.MagicMock(
            to_database=mocker.MagicMock(return_value=({}, "{}")), totals=ReportTotals()
        )
        mocked_2.side_effect = [
            (false_report, mocker.MagicMock(id=1, totals=ReportTotals())),
            ReportEmptyError(),
        ]
        mocked_4 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_, files_array=[])
        dbsession.add(report_details)
        dbsession.flush()
        redis_queue = [
            {"url": "url", "what": "huh"},
            {"url": "url2", "extra_param": 45},
        ]
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [
                {"arguments": {"url": "url", "what": "huh"}, "successful": True},
                {
                    "arguments": {"extra_param": 45, "url": "url2"},
                    "error_type": "report_empty",
                    "report": None,
                    "should_retry": False,
                    "successful": False,
                },
            ]
        }
        assert expected_result == result
        assert commit.state == "complete"

    @pytest.mark.asyncio
    async def test_upload_task_call_no_succesful_report(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(
            UploadProcessorTask, "do_process_individual_report"
        )
        mocked_2.side_effect = [ReportEmptyError(), ReportExpiredException()]
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_4 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_4.send_task.return_value = True
        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_, files_array=[])
        dbsession.add(report_details)
        dbsession.flush()
        redis_queue = [
            {"url": "url", "what": "huh"},
            {"url": "url2", "extra_param": 45},
        ]
        result = await UploadProcessorTask().run_async(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [
                {
                    "arguments": {"url": "url", "what": "huh"},
                    "error_type": "report_empty",
                    "report": None,
                    "should_retry": False,
                    "successful": False,
                },
                {
                    "arguments": {"extra_param": 45, "url": "url2"},
                    "error_type": "report_expired",
                    "report": None,
                    "should_retry": False,
                    "successful": False,
                },
            ]
        }
        assert expected_result == result
        assert commit.state == "error"

    @pytest.mark.asyncio
    async def test_save_report_results_apply_diff_not_there(
        self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage
    ):
        commit = CommitFactory.create(
            message="",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        report = Report()
        report_file_1 = ReportFile("path/to/first.py")
        report_file_2 = ReportFile("to/second/path.py")
        report_line_1 = ReportLine.create(coverage=1, sessions=[[0, 1]])
        report_line_2 = ReportLine.create(coverage=0, sessions=[[0, 0]])
        report_line_3 = ReportLine.create(coverage=1, sessions=[[0, 1]])
        report_file_1.append(10, report_line_1)
        report_file_1.append(12, report_line_2)
        report_file_2.append(12, report_line_3)
        report.append(report_file_1)
        report.append(report_file_2)
        chunks_archive_service = ArchiveService(commit.repository)
        mock_repo_provider.get_commit_diff.side_effect = TorngitObjectNotFoundError(
            "response", "message"
        )
        result = await UploadProcessorTask().save_report_results(
            db_session=dbsession,
            report_service=ReportService({}),
            repository=commit.repository,
            commit=commit,
            report=report,
            pr=None,
        )
        expected_result = {
            "url": f"v4/repos/{chunks_archive_service.storage_hash}/commits/{commit.commitid}/chunks.txt"
        }
        assert expected_result == result
        assert report.diff_totals is None

    @pytest.mark.asyncio
    async def test_save_report_results_apply_diff_no_bot(
        self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage
    ):
        commit = CommitFactory.create(
            message="",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        mock_get_repo_service = mocker.patch(
            "tasks.upload_processor.get_repo_provider_service"
        )
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        dbsession.add(commit)
        dbsession.flush()
        report = Report()
        report_file_1 = ReportFile("path/to/first.py")
        report_file_2 = ReportFile("to/second/path.py")
        report_line_1 = ReportLine.create(coverage=1, sessions=[[0, 1]])
        report_line_2 = ReportLine.create(coverage=0, sessions=[[0, 0]])
        report_line_3 = ReportLine.create(coverage=1, sessions=[[0, 1]])
        report_file_1.append(10, report_line_1)
        report_file_1.append(12, report_line_2)
        report_file_2.append(12, report_line_3)
        report.append(report_file_1)
        report.append(report_file_2)
        chunks_archive_service = ArchiveService(commit.repository)
        result = await UploadProcessorTask().save_report_results(
            db_session=dbsession,
            report_service=ReportService({}),
            repository=commit.repository,
            commit=commit,
            report=report,
            pr=None,
        )
        expected_result = {
            "url": f"v4/repos/{chunks_archive_service.storage_hash}/commits/{commit.commitid}/chunks.txt"
        }
        assert expected_result == result
        assert report.diff_totals is None

    @pytest.mark.asyncio
    async def test_save_report_results_apply_diff_valid(
        self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage
    ):
        commit = CommitFactory.create(
            message="",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        report = Report()
        report_file_1 = ReportFile("path/to/first.py")
        report_file_2 = ReportFile("to/second/path.py")
        report_line_1 = ReportLine.create(coverage=1, sessions=[[0, 1]])
        report_line_2 = ReportLine.create(coverage=0, sessions=[[0, 0]])
        report_line_3 = ReportLine.create(coverage=1, sessions=[[0, 1]])
        report_file_1.append(10, report_line_1)
        report_file_1.append(12, report_line_2)
        report_file_2.append(12, report_line_3)
        report.append(report_file_1)
        report.append(report_file_2)
        chunks_archive_service = ArchiveService(commit.repository)
        f = {
            "files": {
                "path/to/first.py": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["9", "3", "9", "5"],
                            "lines": [
                                "+sudo: false",
                                "+",
                                " language: python",
                                " ",
                                " python:",
                            ],
                        }
                    ],
                    "stats": {"added": 2, "removed": 0},
                }
            }
        }
        mock_repo_provider.get_commit_diff.return_value = f
        result = await UploadProcessorTask().save_report_results(
            db_session=dbsession,
            report_service=ReportService({}),
            commit=commit,
            repository=commit.repository,
            report=report,
            pr=None,
        )
        expected_result = {
            "url": f"v4/repos/{chunks_archive_service.storage_hash}/commits/{commit.commitid}/chunks.txt"
        }
        assert expected_result == result
        expected_diff_totals = ReportTotals(
            files=1,
            lines=1,
            hits=1,
            misses=0,
            partials=0,
            coverage="100",
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        assert report.diff_totals == expected_diff_totals

    @pytest.mark.asyncio
    async def test_save_report_results_empty_report(
        self, mocker, mock_configuration, dbsession, mock_repo_provider, mock_storage
    ):
        commit = CommitFactory.create(
            message="",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={
                "codecov": {"max_report_age": "1y ago"}
            },  # Sorry for the timebomb
        )
        dbsession.add(commit)
        dbsession.flush()
        report = Report()
        chunks_archive_service = ArchiveService(commit.repository)
        f = {
            "files": {
                "path/to/first.py": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["9", "3", "9", "5"],
                            "lines": [
                                "+sudo: false",
                                "+",
                                " language: python",
                                " ",
                                " python:",
                            ],
                        }
                    ],
                    "stats": {"added": 2, "removed": 0},
                }
            }
        }
        mock_repo_provider.get_commit_diff.return_value = f
        result = await UploadProcessorTask().save_report_results(
            db_session=dbsession,
            report_service=ReportService({}),
            commit=commit,
            repository=commit.repository,
            report=report,
            pr=None,
        )
        expected_result = {
            "url": f"v4/repos/{chunks_archive_service.storage_hash}/commits/{commit.commitid}/chunks.txt"
        }
        assert expected_result == result
        expected_diff_totals = ReportTotals(
            files=0,
            lines=0,
            hits=0,
            misses=0,
            partials=0,
            coverage=None,
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=None,
            complexity_total=None,
            diff=0,
        )
        assert report.diff_totals == expected_diff_totals
        assert commit.state == "error"
