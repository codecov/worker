import base64
import json
import zlib
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from google.protobuf.json_format import MessageToDict
from shared.storage.exceptions import FileNotInStorageError
from time_machine import travel

import generated_proto.testrun.ta_testrun_pb2 as ta_testrun_pb2
from database.models import CommitReport, DailyTestRollup, Test, TestInstance
from database.tests.factories import (
    CommitFactory,
    ReportFactory,
    RepositoryFactory,
    UploadFactory,
)
from tasks.ta_processor import TAProcessorTask

here = Path(__file__)


@pytest.fixture()
def mock_bigquery_service():
    with patch("ta_storage.bq.get_bigquery_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


class TestUploadTestProcessorTask(object):
    @pytest.mark.integration
    @travel("2025-01-01T00:00:00Z", tick=False)
    def test_ta_processor_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        celery_app,
        mock_bigquery_service,
        snapshot,
    ):
        mock_configuration.set_params(
            mock_configuration.params | {"services": {"bigquery": {"enabled": True}}}
        )

        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        assert len(tests) == 0
        assert len(test_instances) == 0

        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_test.json") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)

        repo = RepositoryFactory.create(
            repoid=1,
            owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
            owner__username="joseph-sentry",
            owner__service="github",
            name="codecov-demo",
        )
        dbsession.add(repo)
        dbsession.flush()
        commit = CommitFactory.create(
            message="hello world",
            commitid="cd76b0821854a780b60012aed85af0a8263004ad",
            repository=repo,
        )
        dbsession.add(commit)
        dbsession.flush()
        report = ReportFactory.create(commit=commit)
        dbsession.add(report)
        dbsession.flush()
        upload = UploadFactory.create(storage_path=url, report=report)
        dbsession.add(upload)
        dbsession.flush()
        upload.id_ = 1
        dbsession.flush()

        argument = {"url": url, "upload_id": upload.id_}
        mocker.patch.object(TAProcessorTask, "app", celery_app)

        result = TAProcessorTask().run_impl(
            dbsession,
            repoid=upload.report.commit.repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
            argument=argument,
        )

        assert result is True
        assert upload.state == "v2_processed"

        tests = [
            {
                "repoid": test.repoid,
                "name": test.name,
                "testsuite": test.testsuite,
                "flags_hash": test.flags_hash,
                "framework": test.framework,
                "computed_name": test.computed_name,
                "filename": test.filename,
            }
            for test in dbsession.query(Test).all()
        ]
        test_instances = [
            {
                "test_id": test_instance.test_id,
                "duration_seconds": test_instance.duration_seconds,
                "outcome": test_instance.outcome,
                "upload_id": test_instance.upload_id,
                "failure_message": test_instance.failure_message,
                "branch": test_instance.branch,
                "commitid": test_instance.commitid,
                "repoid": test_instance.repoid,
            }
            for test_instance in dbsession.query(TestInstance).all()
        ]
        rollups = [
            {
                "test_id": rollup.test_id,
                "date": rollup.date.isoformat(),
                "repoid": rollup.repoid,
                "branch": rollup.branch,
                "fail_count": rollup.fail_count,
                "flaky_fail_count": rollup.flaky_fail_count,
                "skip_count": rollup.skip_count,
                "pass_count": rollup.pass_count,
                "last_duration_seconds": rollup.last_duration_seconds,
                "avg_duration_seconds": rollup.avg_duration_seconds,
                "latest_run": rollup.latest_run.isoformat(),
                "commits_where_fail": rollup.commits_where_fail,
            }
            for rollup in dbsession.query(DailyTestRollup).all()
        ]

        assert snapshot("json") == {
            "tests": sorted(tests, key=lambda x: x["name"]),
            "test_instances": sorted(test_instances, key=lambda x: x["test_id"]),
            "rollups": sorted(rollups, key=lambda x: x["test_id"]),
        }
        assert snapshot("bin") == mock_storage.read_file("archive", url)

        mock_bigquery_service.write.assert_called_once_with(
            "codecov_prod", "testruns", ta_testrun_pb2, ANY
        )

        # this gets the bytes argument to the write call
        # it gets the first call
        # then it gets the args because call is a tuple (name, args, kwargs)
        # then it gets the 3rd item in the args tuple which is the bytes arg
        testruns = [
            MessageToDict(
                ta_testrun_pb2.TestRun.FromString(testrun_bytes),
                preserving_proto_field_name=True,
            )
            for testrun_bytes in mock_bigquery_service.mock_calls[0][1][3]
        ]
        assert snapshot("json") == sorted(testruns, key=lambda x: x["name"])

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
        mock_bigquery_service,
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
            side_effect=RuntimeError,
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
        assert upload.state == "v2_processed"

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
        mock_bigquery_service,
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
        snapshot,
        mock_bigquery_service,
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

        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        rollups = dbsession.query(DailyTestRollup).all()

        assert snapshot("json") == {
            "tests": sorted(tests, key=lambda x: x["name"]),
            "test_instances": sorted(test_instances, key=lambda x: x["test_id"]),
            "rollups": sorted(rollups, key=lambda x: x["test_id"]),
        }

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
        mock_bigquery_service,
    ):
        tests = dbsession.query(Test).all()
        test_instances = dbsession.query(TestInstance).all()
        assert len(tests) == 0
        assert len(test_instances) == 0

        url = "v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt"
        with open(here.parent.parent / "samples" / "sample_test.json") as f:
            content = f.read()
            mock_storage.write_file("archive", url, content)
        upload = UploadFactory.create(storage_path=url, state="v2_processed")
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
        mock_bigquery_service,
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
        assert upload.state == "v2_processed"
