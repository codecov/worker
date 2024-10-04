from pathlib import Path

import celery
import pytest
from celery.exceptions import Retry
from redis.exceptions import LockError
from shared.config import get_config
from shared.reports.enums import UploadState
from shared.reports.resources import Report, ReportFile, ReportLine, ReportTotals
from shared.storage.exceptions import FileNotInStorageError
from shared.torngit.exceptions import TorngitObjectNotFoundError
from shared.upload.constants import UploadErrorCode

from database.models import CommitReport, ReportDetails, UploadError
from database.tests.factories import CommitFactory, UploadFactory
from helpers.exceptions import (
    ReportEmptyError,
    ReportExpiredException,
    RepositoryWithoutValidBotError,
)
from helpers.parallel import ParallelProcessing
from rollouts import USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID
from services.archive import ArchiveService
from services.report import ProcessingError, RawReportInfo, ReportService
from services.report.parser.legacy import LegacyReportParser
from services.report.raw_upload_processor import (
    SessionAdjustmentResult,
    UploadProcessingResult,
)
from tasks.upload_processor import UploadProcessorTask

here = Path(__file__)


def test_default_acks_late() -> None:
    task = UploadProcessorTask()
    # task.acks_late is defined at import time, so it's difficult to test
    # This test ensures that, in the absence of config the default is False
    # So we need to explicitly set acks_late
    assert get_config("setup", "tasks", "upload", "acks_late", default=None) is None
    assert task.acks_late == False


class TestUploadProcessorTask(object):
    @pytest.mark.integration
    @pytest.mark.django_db(databases={"default"})
    def test_upload_processor_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocker.patch.object(
            USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID,
            "check_value",
            return_value=False,
        )

        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_uploaded_report_1.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(UploadProcessorTask, "app", celery_app)

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
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        result = UploadProcessorTask().run_impl(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [
                {
                    "arguments": {"upload_pk": upload.id_, "url": url},
                    "successful": True,
                }
            ]
        }
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        assert commit.report_json == {
            "files": {
                "awesome/__init__.py": [
                    0,
                    [0, 14, 10, 4, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    [0, 4, 4, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                ],
                "tests/__init__.py": [
                    1,
                    [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "tests/test_sample.py": [
                    2,
                    [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "N": None,
                    "a": url,
                    "c": None,
                    "e": None,
                    "f": [],
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

        mocked_1.assert_called_with(commit.commitid, None)
        mock_redis.lock.assert_called_with(
            f"upload_processing_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.integration
    @pytest.mark.django_db(databases={"default"})
    def test_upload_processor_task_call_should_delete(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocker.patch.object(
            USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID,
            "check_value",
            return_value=False,
        )

        mock_configuration.set_params(
            {"services": {"minio": {"expire_raw_after_n_days": True}}}
        )
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mock_delete_file = mocker.patch.object(ArchiveService, "delete_file")
        mocked_1.return_value = None
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7F/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_uploaded_report_1.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(UploadProcessorTask, "app", celery_app)

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
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        result = UploadProcessorTask().run_impl(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [
                {
                    "arguments": {"upload_pk": upload.id_, "url": url},
                    "successful": True,
                }
            ]
        }
        mock_delete_file.assert_called()
        assert (
            upload.storage_path
            == "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7F/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        )
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"

        assert commit.report_json == {
            "files": {
                "awesome/__init__.py": [
                    0,
                    [0, 14, 10, 4, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "tests/__init__.py": [
                    1,
                    [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "tests/test_sample.py": [
                    2,
                    [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "N": None,
                    "a": url,
                    "c": None,
                    "e": None,
                    "f": [],
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

        mocked_1.assert_called_with(commit.commitid, None)
        mock_redis.lock.assert_called_with(
            f"upload_processing_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.django_db(databases={"default"})
    def test_upload_processor_call_with_upload_obj(
        self, mocker, mock_configuration, dbsession, mock_storage
    ):
        mocker.patch.object(
            USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID,
            "check_value",
            return_value=False,
        )

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
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        upload = UploadFactory.create(
            report=current_report_row, state="started", storage_path=url
        )
        dbsession.add(upload)
        dbsession.flush()
        with open(
            here.parent.parent / "samples" / "sample_uploaded_report_1.txt", "rb"
        ) as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocked_3 = mocker.patch.object(UploadProcessorTask, "app")
        mocked_3.send_task.return_value = True
        result = UploadProcessorTask().process_upload(
            db_session=dbsession,
            previous_results={},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
            report_code=None,
            parallel_processing=ParallelProcessing.SERIAL,
        )

        assert result == {
            "processings_so_far": [
                {
                    "arguments": {"url": url, "upload_pk": upload.id_},
                    "successful": True,
                }
            ]
        }
        assert commit.message == "dsidsahdsahdsa"
        assert upload.state == "processed"

        assert commit.report_json == {
            "files": {
                "awesome/__init__.py": [
                    0,
                    [0, 14, 10, 4, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "tests/__init__.py": [
                    1,
                    [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "tests/test_sample.py": [
                    2,
                    [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "N": None,
                    "a": url,
                    "c": None,
                    "e": None,
                    "f": [],
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
        mocked_1.assert_called_with(commit.commitid, None)

        # storage is overwritten with parsed contents
        data = mock_storage.read_file("archive", url)
        parsed = LegacyReportParser().parse_raw_report_from_bytes(content)
        assert data == parsed.content().getvalue()

    @pytest.mark.integration
    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_existing_chunks(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocker.patch.object(
            USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID,
            "check_value",
            return_value=False,
        )

        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        with open(here.parent.parent / "samples" / "sample_chunks_1.txt") as f:
            content = f.read()
            mocked_1.return_value = content
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_uploaded_report_1.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        mocker.patch.object(UploadProcessorTask, "app", celery_app)

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
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        upload = UploadFactory.create(
            report=current_report_row, state="started", storage_path=url
        )
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        result = UploadProcessorTask().run_impl(
            dbsession,
            {},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "processings_so_far": [
                {
                    "arguments": {"upload_pk": upload.id_, "url": url},
                    "successful": True,
                }
            ]
        }
        assert expected_result == result
        assert commit.message == "dsidsahdsahdsa"
        mocked_1.assert_called_with(commit.commitid, None)
        mock_redis.lock.assert_called_with(
            f"upload_processing_lock_{commit.repoid}_{commit.commitid}",
            blocking_timeout=5,
            timeout=300,
        )

    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_exception_within_individual_upload(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        commit = CommitFactory.create(
            message="",
            commitid="abf6d4df662c47e32460020ab14abf9303581429",
            repository__owner__unencrypted_oauth_token="testulk3d54rlhxkjyzomq2wh8b7np47xabcrkx8",
            repository__owner__username="ThiagoCodecov",
            repository__yaml={"codecov": {"max_report_age": False}},
        )
        dbsession.add(commit)
        dbsession.flush()
        upload = UploadFactory.create(
            report__commit=commit, state="started", storage_path="url"
        )
        dbsession.add(upload)
        dbsession.flush()

        mocker.patch(
            "services.report.process_raw_upload",
            side_effect=Exception("first", "aruba", "digimon"),
        )
        mocker.patch.object(
            ReportService,
            "parse_raw_report_from_storage",
            return_value="ParsedRawReport()",
        )
        mocker.patch.object(UploadProcessorTask, "save_report_results")

        mocked_post_process = mocker.patch.object(
            UploadProcessorTask, "postprocess_raw_reports"
        )

        redis_queue = [{"url": "url", "upload_pk": upload.id_}]
        result = UploadProcessorTask().run_impl(
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
                    "arguments": {"upload_pk": upload.id, "url": "url"},
                    "error": {
                        "code": UploadErrorCode.UNKNOWN_PROCESSING,
                        "params": {"location": "url"},
                    },
                    "successful": False,
                }
            ]
        }

        assert result == expected_result
        assert upload.state_id == UploadState.ERROR.db_id
        assert upload.state == "error"

        error_obj = (
            dbsession.query(UploadError)
            .filter(UploadError.upload_id == upload.id)
            .first()
        )
        assert error_obj is not None
        assert error_obj.error_code == UploadErrorCode.UNKNOWN_PROCESSING

        mocked_post_process.assert_called_with(
            mocker.ANY,
            mocker.ANY,
            [
                RawReportInfo(
                    raw_report="ParsedRawReport()",
                    archive_url="url",
                    upload=upload.external_id,
                    error=ProcessingError(
                        code=UploadErrorCode.UNKNOWN_PROCESSING,
                        params={"location": "url"},
                        is_retryable=False,
                    ),
                )
            ],
        )

    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_with_redis_lock_unobtainable(
        self, mocker, mock_configuration, dbsession, mock_redis, celery_app
    ):
        # Mocking retry to also raise the exception so we can see how it is called
        mocked_3 = mocker.patch.object(UploadProcessorTask, "retry")
        mocked_3.side_effect = celery.exceptions.Retry()
        mocker.patch.object(UploadProcessorTask, "app", celery_app)
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
        upload = UploadFactory.create(
            report__commit=commit, state="started", storage_path="url"
        )
        dbsession.add(upload)
        dbsession.flush()
        mocked_random = mocker.patch("random.randint", return_value=179)
        with pytest.raises(celery.exceptions.Retry):
            UploadProcessorTask().run_impl(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=[{"url": "url", "upload_pk": upload.id_}],
            )
        mocked_3.assert_called_with(countdown=179, max_retries=5)
        mocked_random.assert_called_with(100, 200)

    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_with_expired_report(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocker.patch.object(ArchiveService, "read_file", return_value=b"")
        mocked_2 = mocker.patch("services.report.process_raw_upload")
        false_report = Report()
        false_report_file = ReportFile("file.c")
        false_report_file.append(18, ReportLine.create(1, []))
        false_report.append(false_report_file)
        mocked_2.side_effect = [
            UploadProcessingResult(
                report=false_report, session_adjustment=SessionAdjustmentResult([], [])
            ),
            ReportExpiredException(),
        ]
        # Mocking retry to also raise the exception so we can see how it is called
        mocker.patch.object(UploadProcessorTask, "app", celery_app)
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
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        upload_1 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url"
        )
        upload_2 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url2"
        )
        dbsession.add(upload_1)
        dbsession.add(upload_2)
        dbsession.flush()
        redis_queue = [
            {"url": "url", "what": "huh", "upload_pk": upload_1.id_},
            {"url": "url2", "extra_param": 45, "upload_pk": upload_2.id_},
        ]
        result = UploadProcessorTask().run_impl(
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
                    "arguments": {
                        "url": "url",
                        "what": "huh",
                        "upload_pk": upload_1.id_,
                    },
                    "successful": True,
                },
                {
                    "arguments": {
                        "extra_param": 45,
                        "url": "url2",
                        "upload_pk": upload_2.id_,
                    },
                    "error": {"code": "report_expired", "params": {}},
                    "successful": False,
                },
            ]
        }
        assert expected_result == result
        assert commit.state == "complete"

    def test_upload_task_process_individual_report_with_notfound_report(
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
        false_report = mocker.MagicMock(
            to_database=mocker.MagicMock(return_value=({}, "{}")), totals=ReportTotals()
        )
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
        upload = UploadFactory.create(
            report__commit=commit, storage_path="locationlocation"
        )
        dbsession.add(upload)
        task = UploadProcessorTask()
        task.request.retries = 1
        result = task.process_individual_report(
            report_service=ReportService({"codecov": {"max_report_age": False}}),
            commit=commit,
            report=false_report,
            raw_report_info=RawReportInfo(),
            upload=upload,
            parallel_processing=ParallelProcessing.SERIAL,
        )
        assert result.error.as_dict() == {
            "code": "file_not_in_storage",
            "params": {"location": "locationlocation"},
        }
        assert commit.state == "complete"
        assert upload.state == "error"

    def test_upload_task_process_individual_report_with_notfound_report_no_retries_yet(
        self, mocker
    ):
        # throw an error thats retryable:
        mocker.patch.object(
            ReportService,
            "parse_raw_report_from_storage",
            side_effect=FileNotInStorageError(),
        )
        task = UploadProcessorTask()
        with pytest.raises(Retry):
            task.process_individual_report(
                ReportService({}),
                CommitFactory.create(),
                Report(),
                UploadFactory.create(),
                RawReportInfo(),
                parallel_processing=ParallelProcessing.SERIAL,
            )

    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_with_empty_report(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocker.patch.object(ArchiveService, "read_file", return_value=b"")
        mocked_2 = mocker.patch("services.report.process_raw_upload")
        false_report = Report()
        false_report_file = ReportFile("file.c")
        false_report_file.append(18, ReportLine.create(1, []))
        false_report.append(false_report_file)
        mocked_2.side_effect = [
            UploadProcessingResult(
                report=false_report, session_adjustment=SessionAdjustmentResult([], [])
            ),
            ReportEmptyError(),
        ]
        mocker.patch.object(UploadProcessorTask, "app", celery_app)
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
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        upload_1 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url"
        )
        upload_2 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url2"
        )
        dbsession.add(upload_1)
        dbsession.add(upload_2)
        dbsession.flush()
        redis_queue = [
            {"url": "url", "what": "huh", "upload_pk": upload_1.id_},
            {"url": "url2", "extra_param": 45, "upload_pk": upload_2.id_},
        ]
        result = UploadProcessorTask().run_impl(
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
                    "arguments": {
                        "url": "url",
                        "what": "huh",
                        "upload_pk": upload_1.id_,
                    },
                    "successful": True,
                },
                {
                    "arguments": {
                        "extra_param": 45,
                        "url": "url2",
                        "upload_pk": upload_2.id_,
                    },
                    "error": {"code": "report_empty", "params": {}},
                    "successful": False,
                },
            ]
        }
        assert expected_result == result
        assert commit.state == "complete"
        assert len(upload_2.errors) == 1
        assert upload_2.errors[0].error_code == "report_empty"
        assert upload_2.errors[0].error_params == {}
        assert upload_2.errors[0].report_upload == upload_2
        assert len(upload_1.errors) == 0

    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_no_successful_report(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch("services.report.process_raw_upload")
        mocker.patch.object(ArchiveService, "read_file", return_value=b"")
        mocked_2.side_effect = [ReportEmptyError(), ReportExpiredException()]
        # Mocking retry to also raise the exception so we can see how it is called
        mocker.patch.object(UploadProcessorTask, "app", celery_app)
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
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        upload_1 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url"
        )
        upload_2 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url2"
        )
        dbsession.add(upload_1)
        dbsession.add(upload_2)
        dbsession.flush()
        redis_queue = [
            {"url": "url", "what": "huh", "upload_pk": upload_1.id_},
            {"url": "url2", "extra_param": 45, "upload_pk": upload_2.id_},
        ]
        result = UploadProcessorTask().run_impl(
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
                    "arguments": {
                        "url": "url",
                        "what": "huh",
                        "upload_pk": upload_1.id_,
                    },
                    "error": {"code": "report_empty", "params": {}},
                    "successful": False,
                },
                {
                    "arguments": {
                        "extra_param": 45,
                        "url": "url2",
                        "upload_pk": upload_2.id_,
                    },
                    "error": {"code": "report_expired", "params": {}},
                    "successful": False,
                },
            ]
        }
        assert expected_result == result
        assert commit.state == "error"
        assert len(upload_2.errors) == 1
        assert upload_2.errors[0].error_code == "report_expired"
        assert upload_2.errors[0].error_params == {}
        assert upload_2.errors[0].report_upload == upload_2
        assert len(upload_1.errors) == 1
        assert upload_1.errors[0].error_code == "report_empty"
        assert upload_1.errors[0].error_params == {}
        assert upload_1.errors[0].report_upload == upload_1

    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_softtimelimit(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(UploadProcessorTask, "process_individual_report")
        mocked_2.side_effect = celery.exceptions.SoftTimeLimitExceeded("banana")
        # Mocking retry to also raise the exception so we can see how it is called
        mocker.patch.object(UploadProcessorTask, "app", celery_app)
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        upload_1 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url"
        )
        dbsession.add(upload_1)
        dbsession.flush()
        redis_queue = [{"url": "url", "what": "huh", "upload_pk": upload_1.id_}]
        with pytest.raises(celery.exceptions.SoftTimeLimitExceeded, match="banana"):
            UploadProcessorTask().run_impl(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=redis_queue,
            )
        assert commit.state == "error"

    @pytest.mark.django_db(databases={"default"})
    def test_upload_task_call_celeryerror(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        mocked_1 = mocker.patch.object(ArchiveService, "read_chunks")
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(UploadProcessorTask, "process_individual_report")
        mocked_2.side_effect = celery.exceptions.Retry("banana")
        # Mocking retry to also raise the exception so we can see how it is called
        mocker.patch.object(UploadProcessorTask, "app", celery_app)
        commit = CommitFactory.create(state="pending")
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(
            report_id=current_report_row.id_, _files_array=[]
        )
        dbsession.add(report_details)
        dbsession.flush()
        upload_1 = UploadFactory.create(
            report=current_report_row, state="started", storage_path="url"
        )
        dbsession.add(upload_1)
        dbsession.flush()
        redis_queue = [{"url": "url", "what": "huh", "upload_pk": upload_1.id_}]
        with pytest.raises(celery.exceptions.Retry, match="banana"):
            UploadProcessorTask().run_impl(
                dbsession,
                {},
                repoid=commit.repoid,
                commitid=commit.commitid,
                commit_yaml={},
                arguments_list=redis_queue,
            )
        assert commit.state == "pending"

    def test_save_report_results_apply_diff_not_there(
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
        result = UploadProcessorTask().save_report_results(
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

    def test_save_report_results_apply_diff_no_bot(
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
        result = UploadProcessorTask().save_report_results(
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

    def test_save_report_results_apply_diff_valid(
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
        result = UploadProcessorTask().save_report_results(
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

    def test_save_report_results_empty_report(
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
        result = UploadProcessorTask().save_report_results(
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

    @pytest.mark.parametrize(
        "pr_value, expected_pr_result", [(1, 1), ("1", 1), ("true", None), ([], None)]
    )
    def test_save_report_results_pr_values(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_repo_provider,
        mock_storage,
        pr_value,
        expected_pr_result,
    ):
        commit = CommitFactory.create(pullid=None)
        dbsession.add(commit)
        dbsession.flush()
        report = mocker.Mock()
        mock_repo_provider.get_commit_diff.return_value = {
            "files": {"path/to/first.py": {}}
        }
        mock_report_service = mocker.Mock(save_report=mocker.Mock(return_value="aaaa"))
        result = UploadProcessorTask().save_report_results(
            db_session=dbsession,
            report_service=mock_report_service,
            commit=commit,
            repository=commit.repository,
            report=report,
            pr=pr_value,
        )
        assert "aaaa" == result
        assert commit.pullid == expected_pr_result
