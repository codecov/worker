from pathlib import Path

import pytest
from celery.exceptions import Retry
from shared.storage.exceptions import FileNotInStorageError

from database.models import CommitReport
from database.models.reports import Test
from database.tests.factories import CommitFactory, UploadFactory
from tasks.test_results_processor import ParserFailureError, TestResultsProcessorTask

here = Path(__file__)


class TestUploadTestProcessorTask(object):
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
        celery_app,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_test.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)

        commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="joseph-sentry",
            repository__owner__service="github",
            repository__name="codecov-demo",
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        result = await TestResultsProcessorTask().run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "successful": True,
            "testrun_list": [
                {
                    "duration_seconds": 0.001,
                    "name": "api.temp.calculator.test_calculator::test_add",
                    "outcome": "Outcome.Pass",
                    "testsuite": "pytest",
                    "failure_message": None,
                },
                {
                    "duration_seconds": 0.001,
                    "name": "api.temp.calculator.test_calculator::test_subtract",
                    "outcome": "Outcome.Pass",
                    "testsuite": "pytest",
                    "failure_message": None,
                },
                {
                    "duration_seconds": 0.0,
                    "name": "api.temp.calculator.test_calculator::test_multiply",
                    "outcome": "Outcome.Pass",
                    "testsuite": "pytest",
                    "failure_message": None,
                },
                {
                    "duration_seconds": 0.001,
                    "name": "api.temp.calculator.test_calculator::test_divide",
                    "outcome": "Outcome.Failure",
                    "testsuite": "pytest",
                    "failure_message": "def test_divide():\n&gt;       assert Calculator.divide(1, 2) == 0.5\nE       assert 1.0 == 0.5\nE        +  where 1.0 = &lt;function Calculator.divide at 0x104c9eb90&gt;(1, 2)\nE        +    where &lt;function Calculator.divide at 0x104c9eb90&gt; = Calculator.divide\n\napi/temp/calculator/test_calculator.py:30: AssertionError",
                },
            ],
        }
        assert expected_result == result
        assert commit.message == "hello world"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_processor_task_call_pytest_reportlog(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_pytest_reportlog.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)

        commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="joseph-sentry",
            repository__owner__service="github",
            repository__name="codecov-demo",
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        result = await TestResultsProcessorTask().run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "successful": True,
            "testrun_list": [
                {
                    "duration_seconds": 0.0009641647338867188,
                    "name": "TestParsers.test_junit[./tests/junit.xml-expected0]",
                    "outcome": "Outcome.Pass",
                    "testsuite": "tests/test_parsers.py",
                    "failure_message": None,
                },
                {
                    "duration_seconds": 0.0008068084716796875,
                    "name": "TestParsers.test_junit[./tests/jest-junit.xml-expected1]",
                    "outcome": "Outcome.Pass",
                    "testsuite": "tests/test_parsers.py",
                    "failure_message": None,
                },
            ],
        }
        assert expected_result == result
        assert commit.message == "hello world"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upload_processor_task_call_vitest(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_vitest.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)

        commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="joseph-sentry",
            repository__owner__service="github",
            repository__name="codecov-demo",
        )
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        result = await TestResultsProcessorTask().run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "successful": True,
            "testrun_list": [
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
            ],
        }
        assert expected_result == result
        assert commit.message == "hello world"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_test_result_processor_task_error_parsing(
        self,
        caplog,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_vitest.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)
        mocker.patch.object(
            TestResultsProcessorTask,
            "process_individual_arg",
            side_effect=ParserFailureError,
        )

        commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="joseph-sentry",
            repository__owner__service="github",
            repository__name="codecov-demo",
        )

        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()

        result = await TestResultsProcessorTask().run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )

        assert result == {"successful": False}
        assert "Error parsing testruns" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_test_result_processor_task_delete_archive(
        self,
        caplog,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_vitest.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)
        mocker.patch.object(
            TestResultsProcessorTask, "should_delete_archive", return_value=True
        )

        commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="joseph-sentry",
            repository__owner__service="github",
            repository__name="codecov-demo",
        )

        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        result = await TestResultsProcessorTask().run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {
            "successful": True,
            "testrun_list": [
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
                {
                    "duration_seconds": 0.009,
                    "name": " first test file 2 + 2 should equal 4",
                    "outcome": "Outcome.Failure",
                    "testsuite": "/root-directory/__tests__/test-file-1.test.ts",
                    "failure_message": "expected 5 to be 4 // Object.is equality",
                },
            ],
        }

        assert expected_result == result
        assert "Deleting uploaded file as requested" in caplog.text
        with pytest.raises(FileNotInStorageError):
            mock_storage.read_file("archive", url)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_test_result_processor_task_bad_file(
        self,
        caplog,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        mock_storage.write_file(
            "archive",
            url,
            b'{"test_results_files": [{"filename": "blah", "format": "blah", "data": "eJxLyknMSIJiAB8CBMY="}]}',
        )
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)

        commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="joseph-sentry",
            repository__owner__service="github",
            repository__name="codecov-demo",
        )

        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        result = await TestResultsProcessorTask().run_async(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = {"successful": False}

        assert expected_result == result
        assert "File did not match any parser format" in caplog.text
