from pathlib import Path

import pytest
from shared.storage.exceptions import FileNotInStorageError
from test_results_parser import Outcome

from database.models import CommitReport
from database.models.reports import Test, TestInstance
from database.tests.factories import CommitFactory, UploadFactory
from services.test_results import generate_test_id
from tasks.test_results_processor import (
    ParserError,
    ParserNotSupportedError,
    TestResultsProcessorTask,
)

here = Path(__file__)


class TestUploadTestProcessorTask(object):
    @pytest.mark.integration
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
        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        assert len(tests) == 0
        assert len(test_instances) == 0

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
        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=upload.report.commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]
        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        failures = (
            dbsession.query(TestInstance).filter_by(outcome=str(Outcome.Failure)).all()
        )

        assert len(tests) == 4
        assert len(test_instances) == 4
        assert len(failures) == 1

        assert (
            failures[0].failure_message
            == """def test_divide():\n&gt;       assert Calculator.divide(1, 2) == 0.5\nE       assert 1.0 == 0.5\nE        +  where 1.0 = &lt;function Calculator.divide at 0x104c9eb90&gt;(1, 2)\nE        +    where &lt;function Calculator.divide at 0x104c9eb90&gt; = Calculator.divide\n\napi/temp/calculator/test_calculator.py:30: AssertionError"""
        )
        assert (
            failures[0].test.name
            == "api.temp.calculator.test_calculator\x1ftest_divide"
        )
        assert expected_result == result
        assert commit.message == "hello world"

    @pytest.mark.integration
    def test_upload_processor_task_call_pytest_reportlog(
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
        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]

        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        failures = (
            dbsession.query(TestInstance).filter_by(outcome=str(Outcome.Failure)).all()
        )

        assert len(tests) == 2
        assert len(test_instances) == 2
        assert len(failures) == 0

        assert (
            tests[0].flags_hash
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert test_instances[0].test.id == tests[0].id
        assert test_instances[0].commitid == commit.commitid
        assert test_instances[0].branch == commit.branch
        assert test_instances[0].repoid == commit.repoid
        assert expected_result == result
        assert commit.message == "hello world"

    @pytest.mark.integration
    def test_upload_processor_task_call_vitest(
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
        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]

        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        failures = (
            dbsession.query(TestInstance).filter_by(outcome=str(Outcome.Failure)).all()
        )

        assert len(tests) == 1
        assert len(test_instances) == 4
        assert len(failures) == 4

        assert (
            tests[0].flags_hash
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert test_instances[0].test.id == tests[0].id

        assert expected_result == result
        assert commit.message == "hello world"

    @pytest.mark.integration
    def test_test_result_processor_task_error_report_matching(
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
            "match_report",
            side_effect=ParserNotSupportedError(),
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

        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        print(caplog.text)
        assert "File did not match any parser format" in caplog.text

    @pytest.mark.integration
    def test_test_result_processor_task_error_parsing_file(
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
            "match_report",
            return_value=("test_parser", mocker.MagicMock(side_effect=ParserError)),
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

        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        print(caplog.text)
        assert "Error parsing file" in caplog.text

    @pytest.mark.integration
    def test_test_result_processor_task_delete_archive(
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
        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]

        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        failures = (
            dbsession.query(TestInstance).filter_by(outcome=str(Outcome.Failure)).all()
        )

        assert len(tests) == 1
        assert len(test_instances) == 4
        assert len(failures) == 4

        assert (
            tests[0].flags_hash
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert test_instances[0].test.id == tests[0].id
        assert expected_result == result
        assert "Deleting uploaded file as requested" in caplog.text
        with pytest.raises(FileNotInStorageError):
            mock_storage.read_file("archive", url)

    @pytest.mark.integration
    def test_test_result_processor_task_bad_file(
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
        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [{"successful": False}]

        assert expected_result == result
        assert "File did not match any parser format" in caplog.text

    @pytest.mark.integration
    def test_upload_processor_task_call_existing_test(
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
        upload = UploadFactory.create(
            storage_path=url,
        )
        dbsession.add(upload)
        dbsession.flush()
        repoid = upload.report.commit.repoid
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

        test_id = generate_test_id(
            repoid,
            "pytest",
            "api.temp.calculator.test_calculator\x1ftest_divide",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        existing_test = Test(
            repoid=repoid,
            flags_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            name="api.temp.calculator.test_calculator\x1ftest_divide",
            testsuite="pytest",
            id_=test_id,
        )
        dbsession.add(existing_test)
        dbsession.flush()

        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]
        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        failures = (
            dbsession.query(TestInstance).filter_by(outcome=str(Outcome.Failure)).all()
        )

        assert len(tests) == 4
        assert len(test_instances) == 4
        assert len(failures) == 1

        assert (
            failures[0].failure_message
            == """def test_divide():\n&gt;       assert Calculator.divide(1, 2) == 0.5\nE       assert 1.0 == 0.5\nE        +  where 1.0 = &lt;function Calculator.divide at 0x104c9eb90&gt;(1, 2)\nE        +    where &lt;function Calculator.divide at 0x104c9eb90&gt; = Calculator.divide\n\napi/temp/calculator/test_calculator.py:30: AssertionError"""
        )
        assert (
            failures[0].test.name
            == "api.temp.calculator.test_calculator\x1ftest_divide"
        )
        assert expected_result == result
        assert commit.message == "hello world"

    @pytest.mark.integration
    def test_upload_processor_task_call_existing_test_diff_flags_hash(
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
        upload = UploadFactory.create(
            storage_path=url,
        )
        dbsession.add(upload)
        dbsession.flush()
        repoid = upload.report.commit.repoid
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

        test_id = generate_test_id(
            repoid,
            "pytest",
            "api.temp.calculator.test_calculator\x1ftest_divide",
            "",
        )
        existing_test = Test(
            repoid=repoid,
            flags_hash="",
            name="api.temp.calculator.test_calculator\x1ftest_divide",
            testsuite="pytest",
            id_=test_id,
        )
        dbsession.add(existing_test)
        dbsession.flush()

        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]
        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        failures = (
            dbsession.query(TestInstance)
            .filter(TestInstance.outcome == str(Outcome.Failure))
            .all()
        )

        assert len(tests) == 5
        assert len(test_instances) == 4
        assert len(failures) == 1

        assert (
            failures[0].failure_message
            == """def test_divide():\n&gt;       assert Calculator.divide(1, 2) == 0.5\nE       assert 1.0 == 0.5\nE        +  where 1.0 = &lt;function Calculator.divide at 0x104c9eb90&gt;(1, 2)\nE        +    where &lt;function Calculator.divide at 0x104c9eb90&gt; = Calculator.divide\n\napi/temp/calculator/test_calculator.py:30: AssertionError"""
        )
        assert (
            failures[0].test.name
            == "api.temp.calculator.test_calculator\x1ftest_divide"
        )
        assert expected_result == result
        assert commit.message == "hello world"
