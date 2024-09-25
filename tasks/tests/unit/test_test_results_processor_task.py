from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from shared.storage.exceptions import FileNotInStorageError
from test_results_parser import Outcome
from time_machine import travel

from database.models import CommitReport
from database.models.reports import DailyTestRollup, Test, TestInstance
from database.tests.factories import CommitFactory, UploadFactory
from database.tests.factories.reports import FlakeFactory
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

        assert result == expected_result

        assert len(tests) == 1
        assert len(test_instances) == 4
        assert len(failures) == 4

        assert (
            tests[0].flags_hash
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert test_instances[0].test.id == tests[0].id
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

    @pytest.mark.integration
    def test_upload_processor_task_call_daily_test_totals(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
    ):
        traveller = travel("1970-1-1T00:00:00Z", tick=False)
        traveller.start()
        first_url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_multi_test_part_1.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", first_url, content)

        first_commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            repository__owner__username="joseph-sentry",
            repository__owner__service="github",
            repository__name="codecov-demo",
            branch="first_branch",
        )
        dbsession.add(first_commit)
        dbsession.flush()

        first_report_row = CommitReport(commit_id=first_commit.id_)
        dbsession.add(first_report_row)
        dbsession.flush()

        upload = UploadFactory.create(storage_path=first_url, report=first_report_row)
        dbsession.add(upload)
        dbsession.flush()

        repoid = upload.report.commit.repoid
        redis_queue = [{"url": first_url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)

        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=repoid,
            commitid=first_commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]

        rollups = dbsession.query(DailyTestRollup).all()

        assert [r.branch for r in rollups] == [
            "first_branch",
            "first_branch",
        ]

        assert [r.date for r in rollups] == [
            date.today(),
            date.today(),
        ]

        traveller.stop()

        traveller = travel("1970-1-2T00:00:00Z", tick=False)
        traveller.start()

        second_commit = CommitFactory.create(
            message="hello world 2",
            commitid="bd76b0821854a780b60012aed85af0a8263004ad",
            repository=first_commit.repository,
            branch="second_branch",
        )
        dbsession.add(second_commit)
        dbsession.flush()

        second_report_row = CommitReport(commit_id=second_commit.id_)
        dbsession.add(second_report_row)
        dbsession.flush()

        second_url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/b84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_multi_test_part_2.txt") as f:
            content = f.read()
            mock_storage.write_file("archive", second_url, content)
        upload = UploadFactory.create(storage_path=second_url, report=second_report_row)
        dbsession.add(upload)
        dbsession.flush()

        tests = dbsession.query(Test).all()
        for test in tests:
            flake = FlakeFactory.create(test=test)
            dbsession.add(flake)
            dbsession.flush()

        redis_queue = [{"url": second_url, "upload_pk": upload.id_}]

        result = TestResultsProcessorTask().run_impl(
            dbsession,
            repoid=repoid,
            commitid=second_commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            arguments_list=redis_queue,
        )
        expected_result = [
            {
                "successful": True,
            }
        ]

        rollups: list[DailyTestRollup] = dbsession.query(DailyTestRollup).all()

        assert result == expected_result

        assert [r.branch for r in rollups] == [
            "first_branch",
            "first_branch",
            "second_branch",
            "second_branch",
        ]

        assert [r.date for r in rollups] == [
            date.today() - timedelta(days=1),
            date.today() - timedelta(days=1),
            date.today(),
            date.today(),
        ]

        assert [r.fail_count for r in rollups] == [1, 0, 0, 1]
        assert [r.pass_count for r in rollups] == [1, 1, 2, 0]
        assert [r.skip_count for r in rollups] == [0, 0, 0, 0]
        assert [r.flaky_fail_count for r in rollups] == [0, 0, 0, 1]

        assert [r.commits_where_fail for r in rollups] == [
            ["cd76b0821854a780b60012aed85af0a8263004ad"],
            [],
            [],
            ["bd76b0821854a780b60012aed85af0a8263004ad"],
        ]

        assert [r.latest_run for r in rollups] == [
            datetime(1970, 1, 1, 0, 0),
            datetime(1970, 1, 1, 0, 0),
            datetime(1970, 1, 2, 0, 0),
            datetime(1970, 1, 2, 0, 0),
        ]
        assert [r.avg_duration_seconds for r in rollups] == [0.001, 7.2, 0.002, 3.6]
        assert [r.last_duration_seconds for r in rollups] == [0.001, 7.2, 0.002, 3.6]
        traveller.stop()
