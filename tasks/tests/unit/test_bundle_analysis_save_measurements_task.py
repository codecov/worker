from shared.bundle_analysis.storage import get_bucket_name

from database.models import CommitReport
from database.tests.factories import CommitFactory, UploadFactory
from services.bundle_analysis.report import ProcessingResult
from tasks.bundle_analysis_save_measurements import BundleAnalysisSaveMeasurementsTask


def test_bundle_analysis_save_measurements_task_success(
    mocker, dbsession, mock_storage, celery_app
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(BundleAnalysisSaveMeasurementsTask, "app", celery_app)

    commit = CommitFactory.create(state="complete")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    save_measurements_mock = mocker.patch(
        "services.bundle_analysis.report.BundleAnalysisReportService.save_measurements"
    )
    save_measurements_mock.return_value = ProcessingResult(
        upload=upload, commit=commit, error=None
    )

    result = BundleAnalysisSaveMeasurementsTask().run_impl(
        dbsession,
        repoid=commit.repoid,
        commitid=commit.commitid,
        uploadid=upload.id_,
        commit_yaml={},
        previous_result=[{"upload_id": upload.id_, "session_id": 28, "error": None}],
    )
    assert result == {"successful": True}


def test_bundle_analysis_save_measurements_task_no_uploads_success(
    mocker, dbsession, mock_storage, celery_app
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(BundleAnalysisSaveMeasurementsTask, "app", celery_app)

    commit = CommitFactory.create(state="complete")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    save_measurements_mock = mocker.patch(
        "services.bundle_analysis.report.BundleAnalysisReportService.save_measurements"
    )
    save_measurements_mock.return_value = ProcessingResult(
        upload=None, commit=commit, error=None
    )

    result = BundleAnalysisSaveMeasurementsTask().run_impl(
        dbsession,
        repoid=commit.repoid,
        commitid=commit.commitid,
        uploadid=None,
        commit_yaml={},
        previous_result=[{"upload_id": None, "session_id": 28, "error": None}],
    )
    assert result == {"successful": True}


def test_bundle_analysis_save_measurements_task_error_from_save_service(
    mocker, dbsession, mock_storage, celery_app
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(BundleAnalysisSaveMeasurementsTask, "app", celery_app)

    commit = CommitFactory.create(state="complete")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    save_measurements_mock = mocker.patch(
        "services.bundle_analysis.report.BundleAnalysisReportService.save_measurements"
    )
    save_measurements_mock.return_value = ProcessingResult(
        upload=upload, commit=commit, error=True
    )

    result = BundleAnalysisSaveMeasurementsTask().run_impl(
        dbsession,
        repoid=commit.repoid,
        commitid=commit.commitid,
        uploadid=upload.id_,
        commit_yaml={},
        previous_result=[{"upload_id": upload.id_, "session_id": 28, "error": False}],
    )
    assert result == {"successful": False}


def test_bundle_analysis_save_measurements_task_error_from_processor_task(
    mocker, dbsession, mock_storage, celery_app
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    mocker.patch.object(BundleAnalysisSaveMeasurementsTask, "app", celery_app)

    commit = CommitFactory.create(state="complete")
    dbsession.add(commit)
    dbsession.flush()

    commit_report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit_report)
    dbsession.flush()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.flush()

    save_measurements_mock = mocker.patch(
        "services.bundle_analysis.report.BundleAnalysisReportService.save_measurements"
    )
    save_measurements_mock.return_value = ProcessingResult(
        upload=upload, commit=commit, error=None
    )

    result = BundleAnalysisSaveMeasurementsTask().run_impl(
        dbsession,
        repoid=commit.repoid,
        commitid=commit.commitid,
        uploadid=upload.id_,
        commit_yaml={},
        previous_result=[{"upload_id": upload.id_, "session_id": 28, "error": True}],
    )
    assert result == {"successful": False}
