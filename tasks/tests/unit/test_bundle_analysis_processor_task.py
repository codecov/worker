from unittest.mock import ANY

import pytest
from redis.exceptions import LockError
from shared.bundle_analysis.storage import get_bucket_name
from shared.django_apps.bundle_analysis.models import CacheConfig
from shared.storage.exceptions import PutRequestRateLimitError

from database.enums import ReportType
from database.models import CommitReport
from database.tests.factories import CommitFactory, RepositoryFactory, UploadFactory
from services.archive import ArchiveService
from tasks.bundle_analysis_processor import BundleAnalysisProcessorTask
from tasks.bundle_analysis_save_measurements import (
    bundle_analysis_save_measurements_task_name,
)


class MockBundleReport:
    def __init__(self, bundle_name, size):
        self.bundle_name = bundle_name
        self.size = size

    @property
    def name(self):
        return self.bundle_name


class MockBundleAnalysisReport:
    def bundle_reports(self):
        return [
            MockBundleReport("BundleA", 1111),
        ]

    def ingest(self, path):
        return 123, "BundleA"

    def cleanup(self):
        pass

    def delete_bundle_by_name(self, bundle_name):
        pass

    def update_is_cached(self, d):
        pass

    def associate_previous_assets(self, prev_bar):
        pass


@pytest.mark.django_db(databases={"default", "timeseries"})
def test_bundle_analysis_processor_task_success(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    commit = CommitFactory.create(state="pending")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    result = BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": None,
                "session_id": 123,
                "upload_id": upload.id_,
                "bundle_name": "bundle1",
            },
        ],
    }

    assert commit.state == "complete"
    assert upload.state == "processed"


def test_bundle_analysis_processor_task_error(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    commit = CommitFactory.create(state="pending")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(
        storage_path="invalid-storage-path", report=commit_report
    )
    dbsession.add(upload)
    dbsession.flush()

    task = BundleAnalysisProcessorTask()
    retry = mocker.patch.object(task, "retry")

    result = task.run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": {
                    "code": "file_not_in_storage",
                    "params": {"location": "invalid-storage-path"},
                },
                "session_id": None,
                "upload_id": upload.id_,
                "bundle_name": None,
            },
        ],
    }

    assert commit.state == "error"
    assert upload.state == "error"
    retry.assert_called_once_with(countdown=20, max_retries=5)


def test_bundle_analysis_processor_task_general_error(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    process_upload = mocker.patch(
        "services.bundle_analysis.report.BundleAnalysisReportService.process_upload"
    )
    process_upload.side_effect = Exception()

    commit = CommitFactory.create()
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(
        state="started",
        storage_path="invalid-storage-path",
        report=commit_report,
    )
    dbsession.add(upload)
    dbsession.flush()

    task = BundleAnalysisProcessorTask()
    retry = mocker.patch.object(task, "retry")

    with pytest.raises(Exception):
        task.run_impl(
            dbsession,
            {"results": [{"previous": "result"}]},
            repoid=commit.repoid,
            commitid=commit.commitid,
            commit_yaml={},
            params={
                "upload_pk": upload.id_,
                "commit": commit.commitid,
            },
        )

    assert upload.state == "error"
    assert not retry.called


def test_bundle_analysis_process_upload_general_error(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    commit = CommitFactory.create(state="pending")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.side_effect = Exception()

    task = BundleAnalysisProcessorTask()
    retry = mocker.patch.object(task, "retry")

    result = BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )

    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": {
                    "code": "parser_error",
                    "params": {
                        "location": "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite",
                        "plugin_name": "unknown",
                    },
                },
                "session_id": None,
                "upload_id": upload.id_,
                "bundle_name": None,
            },
        ],
    }

    assert not retry.called
    assert upload.state == "error"
    assert commit.state == "error"


def test_bundle_analysis_processor_task_locked(
    mocker,
    dbsession,
    mock_storage,
    mock_redis,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )
    mock_redis.lock.return_value.__enter__.side_effect = LockError()

    commit = CommitFactory.create()
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(
        state="started",
        storage_path=storage_path,
        report=commit_report,
    )
    dbsession.add(upload)
    dbsession.flush()

    task = BundleAnalysisProcessorTask()
    retry = mocker.patch.object(task, "retry")

    result = task.run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result is None

    assert upload.state == "started"
    retry.assert_called_once_with(countdown=ANY, max_retries=5)


def test_bundle_analysis_process_upload_rate_limit_error(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    commit = CommitFactory.create(state="pending")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    task = BundleAnalysisProcessorTask()
    retry = mocker.patch.object(task, "retry")

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.side_effect = PutRequestRateLimitError()

    result = task.run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": {
                    "code": "rate_limit_error",
                    "params": {
                        "location": "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
                    },
                },
                "session_id": None,
                "upload_id": upload.id_,
                "bundle_name": None,
            },
        ],
    }

    assert commit.state == "error"
    assert upload.state == "error"
    retry.assert_called_once_with(countdown=20, max_retries=5)


def test_bundle_analysis_process_associate_no_parent_commit_id(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    parent_commit = CommitFactory.create(state="completed")
    dbsession.add(parent_commit)
    dbsession.flush()

    commit = CommitFactory.create(state="pending", parent_commit_id=None)
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )

    assert commit.state == "complete"
    assert upload.state == "processed"


def test_bundle_analysis_process_associate_no_parent_commit_object(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    parent_commit = CommitFactory.create(state="completed")

    commit = CommitFactory.create(
        state="pending", parent_commit_id=parent_commit.commitid
    )
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )

    assert commit.state == "complete"
    assert upload.state == "processed"


def test_bundle_analysis_process_associate_no_parent_commit_report_object(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    parent_commit = CommitFactory.create(state="completed")
    dbsession.add(parent_commit)
    dbsession.flush()

    commit = CommitFactory.create(
        state="pending",
        parent_commit_id=parent_commit.commitid,
        repository=parent_commit.repository,
    )
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )

    assert commit.state == "complete"
    assert upload.state == "processed"


def test_bundle_analysis_process_associate_called(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    parent_commit = CommitFactory.create(state="completed")
    dbsession.add(parent_commit)
    dbsession.flush()

    parent_commit_report = CommitReport(
        commit_id=parent_commit.id_, report_type="bundle_analysis"
    )
    dbsession.add(parent_commit_report)
    dbsession.flush()

    commit = CommitFactory.create(
        state="pending",
        parent_commit_id=parent_commit.commitid,
        repository=parent_commit.repository,
    )
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )

    assert commit.state == "complete"
    assert upload.state == "processed"


@pytest.mark.django_db(databases={"default", "timeseries"})
def test_bundle_analysis_process_associate_called_two(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    parent_commit = CommitFactory.create(state="completed")
    dbsession.add(parent_commit)
    dbsession.flush()

    parent_commit_report = CommitReport(
        commit_id=parent_commit.id_, report_type="bundle_analysis"
    )
    dbsession.add(parent_commit_report)
    dbsession.flush()

    commit = CommitFactory.create(
        state="pending",
        parent_commit_id=parent_commit.commitid,
        repository=parent_commit.repository,
    )
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    associate = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReport.associate_previous_assets"
    )
    associate.return_value = None

    prev_bundle_report = mocker.patch(
        "services.bundle_analysis.report.BundleAnalysisReportService._previous_bundle_analysis_report"
    )
    prev_bundle_report.side_effect = [None, MockBundleAnalysisReport()]

    BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )

    assert commit.state == "complete"
    assert upload.state == "processed"
    associate.assert_called_once()


def test_bundle_analysis_processor_task_cache_config_not_saved(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
        return_value=MockBundleAnalysisReport(),
    )

    bundle_load_mock_save = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.save",
        return_value=MockBundleAnalysisReport(),
    )
    bundle_load_mock_save.return_value = None

    bundle_config_mock = mocker.patch(
        "shared.django_apps.bundle_analysis.service.bundle_analysis.BundleAnalysisCacheConfigService.update_cache_option"
    )

    commit = CommitFactory.create(state="pending")

    # Using main branch as default and commit is in feat
    commit.branch = "feat"
    commit.repository.branch = "main"

    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    result = BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": None,
                "session_id": 123,
                "upload_id": upload.id_,
                "bundle_name": "BundleA",
            },
        ],
    }

    assert commit.state == "complete"
    assert upload.state == "processed"

    bundle_config_mock.assert_not_called()


def test_bundle_analysis_processor_task_cache_config_saved(
    mocker,
    dbsession,
    mock_storage,
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
        return_value=MockBundleAnalysisReport(),
    )

    bundle_load_mock_save = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.save",
        return_value=MockBundleAnalysisReport(),
    )
    bundle_load_mock_save.return_value = None

    bundle_config_mock = mocker.patch(
        "shared.django_apps.bundle_analysis.service.bundle_analysis.BundleAnalysisCacheConfigService.update_cache_option"
    )

    commit = CommitFactory.create(state="pending")

    # Using main branch as default and commit is in main
    commit.branch = "main"
    commit.repository.branch = "main"

    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    result = BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": None,
                "session_id": 123,
                "upload_id": upload.id_,
                "bundle_name": "BundleA",
            },
        ],
    }

    assert commit.state == "complete"
    assert upload.state == "processed"

    bundle_config_mock.assert_called_with(commit.repository.repoid, "BundleA")


@pytest.mark.django_db(databases={"default", "timeseries"})
def test_bundle_analysis_processor_not_caching_previous_report(
    mocker,
    dbsession,
    mock_storage,
):
    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    repository = RepositoryFactory()

    prev_commit = CommitFactory.create(repository=repository)
    dbsession.add(prev_commit)
    dbsession.flush()

    prev_report = CommitReport(
        commit_id=prev_commit.id_, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(prev_report)
    dbsession.flush()

    commit = CommitFactory.create(
        state="pending", repository=repository, parent_commit_id=prev_commit.commitid
    )
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    repo_key = ArchiveService.get_archive_hash(prev_commit.repository)
    storage_path = (
        f"v1/repos/{repo_key}/{prev_report.external_id}/bundle_report.sqlite",
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    loader_mock = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
    )
    loader_mock.side_effect = [None, MockBundleAnalysisReport(), None]

    saver_mock = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.save",
    )
    saver_mock.return_value = None

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    result = BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": None,
                "session_id": 123,
                "upload_id": upload.id_,
                "bundle_name": "BundleA",
            },
        ],
    }

    assert commit.state == "complete"
    assert upload.state == "processed"


@pytest.mark.django_db(databases={"default", "timeseries"})
def test_bundle_analysis_processor_not_caching_previous_report_two(
    mocker,
    dbsession,
    mock_storage,
):
    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    repository = RepositoryFactory()

    prev_commit = CommitFactory.create(repository=repository)
    dbsession.add(prev_commit)
    dbsession.flush()

    prev_report = CommitReport(
        commit_id=prev_commit.id_, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(prev_report)
    dbsession.flush()

    commit = CommitFactory.create(
        state="pending", repository=repository, parent_commit_id=prev_commit.commitid
    )
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    CacheConfig.objects.create(
        repo_id=commit.repoid, bundle_name="BundleA", is_caching=False
    )

    repo_key = ArchiveService.get_archive_hash(prev_commit.repository)
    storage_path = (
        f"v1/repos/{repo_key}/{prev_report.external_id}/bundle_report.sqlite",
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    loader_mock = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
    )
    loader_mock.side_effect = [None, MockBundleAnalysisReport(), None]

    saver_mock = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.save",
    )
    saver_mock.return_value = None

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    result = BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": None,
                "session_id": 123,
                "upload_id": upload.id_,
                "bundle_name": "BundleA",
            },
        ],
    }

    assert commit.state == "complete"
    assert upload.state == "processed"


@pytest.mark.django_db(databases={"default", "timeseries"})
def test_bundle_analysis_processor_caching_previous_report(
    mocker,
    dbsession,
    mock_storage,
):
    mocker.patch.object(
        BundleAnalysisProcessorTask,
        "app",
        tasks={
            bundle_analysis_save_measurements_task_name: mocker.MagicMock(),
        },
    )

    repository = RepositoryFactory()

    prev_commit = CommitFactory.create(repository=repository)
    dbsession.add(prev_commit)
    dbsession.flush()

    prev_report = CommitReport(
        commit_id=prev_commit.id_, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(prev_report)
    dbsession.flush()

    commit = CommitFactory.create(
        state="pending", repository=repository, parent_commit_id=prev_commit.commitid
    )
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    CacheConfig.objects.create(
        repo_id=commit.repoid, bundle_name="BundleA", is_caching=True
    )

    repo_key = ArchiveService.get_archive_hash(prev_commit.repository)
    storage_path = (
        f"v1/repos/{repo_key}/{prev_report.external_id}/bundle_report.sqlite",
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    loader_mock = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
    )
    loader_mock.side_effect = [None, MockBundleAnalysisReport(), None]

    saver_mock = mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.save",
    )
    saver_mock.return_value = None

    ingest = mocker.patch("shared.bundle_analysis.BundleAnalysisReport.ingest")
    ingest.return_value = (123, "bundle1")  # session_id

    result = BundleAnalysisProcessorTask().run_impl(
        dbsession,
        {"results": [{"previous": "result"}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
        params={
            "upload_pk": upload.id_,
            "commit": commit.commitid,
        },
    )
    assert result == {
        "results": [
            {"previous": "result"},
            {
                "error": None,
                "session_id": 123,
                "upload_id": upload.id_,
                "bundle_name": "BundleA",
            },
        ],
    }

    assert commit.state == "complete"
    assert upload.state == "processed"
