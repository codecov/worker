from datetime import date, datetime, timedelta, timezone
from itertools import chain
from pathlib import Path

import pytest
from shared.storage.exceptions import FileNotInStorageError
from test_results_parser import Outcome
from time_machine import travel

from database.models import CommitReport, RepositoryFlag
from database.models.reports import DailyTestRollup, Test, TestFlagBridge, TestInstance
from database.tests.factories import CommitFactory, UploadFactory
from database.tests.factories.reports import FlakeFactory
from services.test_results import generate_test_id
from tasks.test_results_processor import (
    ParserError,
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
        with open(here.parent.parent / "samples" / "sample_test.json") as f:
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
            == """def test_divide():\n>       assert Calculator.divide(1, 2) == 0.5\nE       assert 1.0 == 0.5\nE        +  where 1.0 = <function Calculator.divide at 0x104c9eb90>(1, 2)\nE        +    where <function Calculator.divide at 0x104c9eb90> = Calculator.divide\n\napi/temp/calculator/test_calculator.py:30: AssertionError"""
        )
        assert (
            failures[0].test.name
            == "api.temp.calculator.test_calculator\x1ftest_divide"
        )
        assert expected_result == result
        assert commit.message == "hello world"
        assert (
            mock_storage.read_file("archive", url)
            == b"""# path=codecov-demo/temp.junit.xml
<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="0" failures="1" skipped="0" tests="4" time="0.052" timestamp="2023-11-06T11:17:04.011072" hostname="VFHNWJDWH9.local"><testcase classname="api.temp.calculator.test_calculator" name="test_add" time="0.001" /><testcase classname="api.temp.calculator.test_calculator" name="test_subtract" time="0.001" /><testcase classname="api.temp.calculator.test_calculator" name="test_multiply" time="0.000" /><testcase classname="api.temp.calculator.test_calculator" name="test_divide" time="0.001"><failure message="assert 1.0 == 0.5&#10; +  where 1.0 = &lt;function Calculator.divide at 0x104c9eb90&gt;(1, 2)&#10; +    where &lt;function Calculator.divide at 0x104c9eb90&gt; = Calculator.divide">def test_divide():
&gt;       assert Calculator.divide(1, 2) == 0.5
E       assert 1.0 == 0.5
E        +  where 1.0 = &lt;function Calculator.divide at 0x104c9eb90&gt;(1, 2)
E        +    where &lt;function Calculator.divide at 0x104c9eb90&gt; = Calculator.divide

api/temp/calculator/test_calculator.py:30: AssertionError</failure></testcase></testsuite></testsuites>
<<<<<< EOF

"""
        )

    @pytest.mark.integration
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
        with open(here.parent.parent / "samples" / "sample_test.json") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        redis_queue = [{"url": url, "upload_pk": upload.id_}]
        mocker.patch.object(TestResultsProcessorTask, "app", celery_app)
        mocker.patch(
            "tasks.test_results_processor.parse_junit_xml",
            side_effect=ParserError,
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
        with open(here.parent.parent / "samples" / "sample_test.json") as f:
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

        assert len(tests) == 4
        assert len(test_instances) == 4
        assert len(failures) == 1

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
        assert (
            "No test result files were successfully parsed for this upload"
            in caplog.text
        )

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
        with open(here.parent.parent / "samples" / "sample_test.json") as f:
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
            == """def test_divide():\n>       assert Calculator.divide(1, 2) == 0.5\nE       assert 1.0 == 0.5\nE        +  where 1.0 = <function Calculator.divide at 0x104c9eb90>(1, 2)\nE        +    where <function Calculator.divide at 0x104c9eb90> = Calculator.divide\n\napi/temp/calculator/test_calculator.py:30: AssertionError"""
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
        with open(here.parent.parent / "samples" / "sample_test.json") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(
            storage_path=url,
        )
        dbsession.add(upload)
        dbsession.flush()
        repoid = upload.report.commit.repoid
        repo_flag = RepositoryFlag(
            repository=upload.report.commit.repository, flag_name="hello_world"
        )
        upload.flags = [repo_flag]
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

        test_flag_bridges = dbsession.query(TestFlagBridge).all()

        assert set(bridge.test_id for bridge in test_flag_bridges) == set(
            instance.test_id for instance in test_instances
        )
        for bridge in test_flag_bridges:
            assert bridge.flag == repo_flag

        assert len(tests) == 5
        assert len(test_instances) == 4
        assert len(failures) == 1

        assert (
            failures[0].failure_message
            == """def test_divide():\n>       assert Calculator.divide(1, 2) == 0.5\nE       assert 1.0 == 0.5\nE        +  where 1.0 = <function Calculator.divide at 0x104c9eb90>(1, 2)\nE        +    where <function Calculator.divide at 0x104c9eb90> = Calculator.divide\n\napi/temp/calculator/test_calculator.py:30: AssertionError"""
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
        with travel("1970-1-1T00:00:00Z", tick=False):
            first_url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
            with open(
                here.parent.parent / "samples" / "sample_multi_test_part_1.json"
            ) as f:
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

            upload = UploadFactory.create(
                storage_path=first_url, report=first_report_row
            )
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

        with travel("1970-1-2T00:00:00Z", tick=False):
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
            with open(
                here.parent.parent / "samples" / "sample_multi_test_part_2.json"
            ) as f:
                content = f.read()
                mock_storage.write_file("archive", second_url, content)
            upload = UploadFactory.create(
                storage_path=second_url, report=second_report_row
            )
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

            assert result == expected_result

            rollups_first_branch: list[DailyTestRollup] = (
                dbsession.query(DailyTestRollup).filter_by(branch="first_branch").all()
            )

            assert set(r.date for r in rollups_first_branch) == {
                date.today() - timedelta(days=1)
            }
            assert set(r.fail_count for r in rollups_first_branch) == {0, 1}
            assert set(r.pass_count for r in rollups_first_branch) == {1}
            assert set(r.skip_count for r in rollups_first_branch) == {0}
            assert set(r.flaky_fail_count for r in rollups_first_branch) == {0}
            assert set(
                chain.from_iterable(r.commits_where_fail for r in rollups_first_branch)
            ) == {
                "cd76b0821854a780b60012aed85af0a8263004ad",
            }
            assert set(r.latest_run for r in rollups_first_branch) == {
                datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)
            }
            assert set(r.avg_duration_seconds for r in rollups_first_branch) == {
                7.2,
                0.001,
            }
            assert set(r.last_duration_seconds for r in rollups_first_branch) == {
                7.2,
                0.001,
            }

            rollups_second_branch: list[DailyTestRollup] = (
                dbsession.query(DailyTestRollup).filter_by(branch="second_branch").all()
            )

            assert set(r.date for r in rollups_second_branch) == {date.today()}
            assert set(r.fail_count for r in rollups_second_branch) == {0, 1}
            assert set(r.pass_count for r in rollups_second_branch) == {0, 2}
            assert set(r.skip_count for r in rollups_second_branch) == {0}
            assert set(r.flaky_fail_count for r in rollups_second_branch) == {0, 1}
            assert set(
                chain.from_iterable(r.commits_where_fail for r in rollups_second_branch)
            ) == {
                "bd76b0821854a780b60012aed85af0a8263004ad",
            }
            assert set(r.latest_run for r in rollups_second_branch) == {
                datetime(1970, 1, 2, 0, 0, tzinfo=timezone.utc)
            }
            assert set(r.avg_duration_seconds for r in rollups_second_branch) == {
                3.6,
                0.002,
            }
            assert set(r.last_duration_seconds for r in rollups_second_branch) == {
                3.6,
                0.002,
            }

    @pytest.mark.integration
    def test_upload_processor_task_call_network(
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
        with open(
            here.parent.parent / "samples" / "sample_test_missing_network.json"
        ) as f:
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

        for test in tests:
            assert test.framework == "Pytest"
            assert test.computed_name.startswith(
                "api/temp/calculator/test_calculator.py::"
            )

        assert (
            failures[0].failure_message.replace(" ", "").replace("\n", "")
            == """deftest_divide():>assertCalculator.divide(1,2)==0.5Eassert1.0==0.5E+where1.0=<functionCalculator.divideat0x104c9eb90>(1,2)E+where<functionCalculator.divideat0x104c9eb90>=Calculator.divideapi/temp/calculator/test_calculator.py:30:AssertionError"""
        )
        assert (
            failures[0].test.name
            == "api.temp.calculator.test_calculator\x1ftest_divide"
        )
        assert expected_result == result
        assert commit.message == "hello world"

        assert mock_storage.read_file("archive", url).startswith(
            b"""# path=codecov-demo/temp.junit.xml
"""
        )
