import base64
import json
import zlib
from pathlib import Path

import msgpack
import pytest
from shared.storage.exceptions import FileNotInStorageError
from test_results_parser import ParserError

from database.models import CommitReport
from database.models.reports import Test, TestInstance
from database.tests.factories import CommitFactory, UploadFactory
from services.redis import get_redis_connection
from tasks.ta_processor import TAProcessorTask

here = Path(__file__)


class TestUploadTestProcessorTask(object):
    @pytest.mark.integration
    def test_ta_processor_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
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
        argument = {"url": url, "upload_id": upload.id_}
        mocker.patch.object(TAProcessorTask, "app", celery_app)

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
        result = TAProcessorTask().run_impl(
            dbsession,
            repoid=upload.report.commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            argument=argument,
        )

        assert result is True
        assert upload.state == "processed"

        redis = get_redis_connection()
        a = redis.get(
            f"ta/intermediate/{upload.report.commit.repoid}/{commit.commitid}/{upload.id_}"
        )
        assert a is not None
        assert msgpack.unpackb(a) == [
            {
                "framework": "Pytest",
                "testruns": [
                    {
                        "name": "test_add",
                        "classname": "api.temp.calculator.test_calculator",
                        "duration": 0.001,
                        "outcome": "pass",
                        "testsuite": "pytest",
                        "failure_message": None,
                        "filename": None,
                        "build_url": None,
                        "computed_name": "api.temp.calculator.test_calculator::test_add",
                    },
                    {
                        "name": "test_subtract",
                        "classname": "api.temp.calculator.test_calculator",
                        "duration": 0.001,
                        "outcome": "pass",
                        "testsuite": "pytest",
                        "failure_message": None,
                        "filename": None,
                        "build_url": None,
                        "computed_name": "api.temp.calculator.test_calculator::test_subtract",
                    },
                    {
                        "name": "test_multiply",
                        "classname": "api.temp.calculator.test_calculator",
                        "duration": 0.0,
                        "outcome": "pass",
                        "testsuite": "pytest",
                        "failure_message": None,
                        "filename": None,
                        "build_url": None,
                        "computed_name": "api.temp.calculator.test_calculator::test_multiply",
                    },
                    {
                        "name": "test_divide",
                        "classname": "api.temp.calculator.test_calculator",
                        "duration": 0.001,
                        "outcome": "failure",
                        "testsuite": "pytest",
                        "failure_message": """def test_divide():
>       assert Calculator.divide(1, 2) == 0.5
E       assert 1.0 == 0.5
E        +  where 1.0 = <function Calculator.divide at 0x104c9eb90>(1, 2)
E        +    where <function Calculator.divide at 0x104c9eb90> = Calculator.divide

api/temp/calculator/test_calculator.py:30: AssertionError""",
                        "filename": None,
                        "build_url": None,
                        "computed_name": "api.temp.calculator.test_calculator::test_divide",
                    },
                ],
            }
        ]

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
    def test_ta_processor_task_error_parsing_file(
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
        argument = {"url": url, "upload_id": upload.id_}
        mocker.patch.object(TAProcessorTask, "app", celery_app)
        mocker.patch(
            "tasks.ta_processor.parse_raw_upload",
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

        result = TAProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            argument=argument,
        )

        assert result is False
        assert upload.state == "has_failed"

    @pytest.mark.integration
    def test_ta_processor_task_delete_archive(
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
        argument = {"url": url, "upload_id": upload.id_}
        mocker.patch.object(TAProcessorTask, "app", celery_app)
        mocker.patch.object(TAProcessorTask, "should_delete_archive", return_value=True)

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
        result = TAProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            argument=argument,
        )

        assert result is True
        with pytest.raises(FileNotInStorageError):
            mock_storage.read_file("archive", url)

    @pytest.mark.integration
    def test_ta_processor_task_bad_file(
        self,
        caplog,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        celery_app,
    ):
        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        mock_storage.write_file(
            "archive",
            url,
            b'{"test_results_files": [{"filename": "blah", "format": "blah", "data": "eJzLSM3JyVcozy/KSQEAGgsEXQ=="}]}',
        )
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()
        argument = {"url": url, "upload_id": upload.id_}
        mocker.patch.object(TAProcessorTask, "app", celery_app)

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
        result = TAProcessorTask().run_impl(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            argument=argument,
        )

        assert result is True
        redis = get_redis_connection()
        result = redis.get(
            f"ta/intermediate/{commit.repoid}/{commit.commitid}/{upload.id_}"
        )
        assert result is not None
        msgpacked = msgpack.unpackb(result)
        assert msgpacked == [
            {
                "framework": None,
                "testruns": [],
            }
        ]

    @pytest.mark.integration
    def test_ta_processor_task_call_already_processed(
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
        upload = UploadFactory.create(storage_path=url, state="processed")
        dbsession.add(upload)
        dbsession.flush()
        argument = {"url": url, "upload_id": upload.id_}
        mocker.patch.object(TAProcessorTask, "app", celery_app)

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
        result = TAProcessorTask().run_impl(
            dbsession,
            repoid=upload.report.commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            argument=argument,
        )

        assert result is False

    @pytest.mark.integration
    def test_ta_processor_task_call_already_processed_with_junit(
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
        with open(here.parent.parent / "samples" / "sample_ta_file.xml") as f:
            content = f.read()
            compressed_and_base64_encoded = base64.b64encode(
                zlib.compress(content.encode("utf-8"))
            ).decode("utf-8")
            thing = {
                "test_results_files": [
                    {
                        "filename": "codecov-demo/temp.junit.xml",
                        "format": "base64+compressed",
                        "data": compressed_and_base64_encoded,
                    }
                ]
            }
            mock_storage.write_file("archive", url, json.dumps(thing))
        upload = UploadFactory.create(storage_path=url)
        dbsession.add(upload)
        dbsession.flush()

        argument = {"url": url, "upload_id": upload.id_}
        mocker.patch.object(TAProcessorTask, "app", celery_app)

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
        result = TAProcessorTask().run_impl(
            dbsession,
            repoid=upload.report.commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            argument=argument,
        )

        assert result is True
        assert upload.state == "processed"
