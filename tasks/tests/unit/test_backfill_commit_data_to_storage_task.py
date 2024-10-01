from unittest.mock import call, patch

from database.models.core import Commit
from database.models.reports import CommitReport, ReportDetails
from database.tests.factories.core import CommitFactory, ReportDetailsFactory
from tasks.backfill_commit_data_to_storage import (
    BackfillCommitDataToStorageTask,
    BackfillError,
)


class TestBackfillCommitDataToStorageTask(object):
    @patch("database.utils.ArchiveService")
    def test_handle_report_json(
        self, mock_archive_service, dbsession, mock_configuration
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "report_details_files_array": "general_access",
                        "commit_report": "general_access",
                    },
                }
            }
        )
        commit = CommitFactory()
        dbsession.add(commit)
        assert commit._report_json is not None
        assert commit._report_json_storage_path is None
        task = BackfillCommitDataToStorageTask()
        result = task.handle_report_json(dbsession, commit)
        assert result == {"success": True, "errors": []}
        assert commit._report_json is None
        assert commit._report_json_storage_path is not None
        mock_archive_service.return_value.write_json_data_to_storage.assert_called()

    @patch("database.utils.ArchiveService")
    def test_handle_report_json_alredy_in_storage(
        self, mock_archive_service, dbsession
    ):
        commit = CommitFactory()
        dbsession.add(commit)
        commit._report_json = None
        commit._report_json_storage_path = "path/to/sotorage"
        task = BackfillCommitDataToStorageTask()
        result = task.handle_report_json(dbsession, commit)
        assert result == {"success": True, "errors": []}
        assert commit._report_json is None
        assert commit._report_json_storage_path == "path/to/sotorage"
        mock_archive_service.return_value.write_json_data_to_storage.assert_not_called()

    def test_handle_report_json_missing_data(self, dbsession):
        commit = CommitFactory()
        dbsession.add(commit)
        commit._report_json = None
        commit._report_json_storage_path = None
        task = BackfillCommitDataToStorageTask()
        result = task.handle_report_json(dbsession, commit)
        assert result == {"success": False, "errors": ["missing_data"]}
        assert commit._report_json is None
        assert commit._report_json_storage_path is None

    @patch(
        "tasks.backfill_commit_data_to_storage.BackfillCommitDataToStorageTask.handle_single_report_row"
    )
    def test_all_report_rows(self, mock_handle_single_row, dbsession):
        def mock_handle_single_row_return_side_effect(db_session, commit, report_row):
            if report_row.code is None:
                return {"success": True, "errors": []}
            if report_row.code == "local":
                return {"success": False, "errors": [BackfillError.missing_data.value]}

        mock_handle_single_row.side_effect = mock_handle_single_row_return_side_effect
        commit = CommitFactory()
        dbsession.add(commit)
        report_default = CommitReport(commit=commit, code=None)
        report_code = CommitReport(commit=commit, code="local")
        dbsession.add(report_default)
        dbsession.add(report_code)
        task = BackfillCommitDataToStorageTask()
        result = task.handle_all_report_rows(dbsession, commit)
        assert result == {"success": False, "errors": ["missing_data"]}
        mock_handle_single_row.assert_has_calls(
            [
                call(dbsession, commit, report_default),
                call(dbsession, commit, report_code),
            ]
        )

    @patch(
        "tasks.backfill_commit_data_to_storage.BackfillCommitDataToStorageTask.handle_single_report_row"
    )
    def test_all_report_rows_no_CommitReport(self, mock_handle_single_row, dbsession):
        commit = CommitFactory()
        dbsession.add(commit)

        def mock_handle_single_row_return_side_effect(
            db_session, received_commit, report_row
        ):
            assert received_commit == commit
            assert isinstance(report_row, CommitReport)
            if report_row.code is None:
                return {"success": True, "errors": []}

        mock_handle_single_row.side_effect = mock_handle_single_row_return_side_effect

        assert commit.reports_list == []
        task = BackfillCommitDataToStorageTask()
        result = task.handle_all_report_rows(dbsession, commit)
        assert result == {"success": True, "errors": []}
        assert mock_handle_single_row.call_count == 1

    @patch("database.utils.ArchiveService")
    def test_handle_single_report_row(
        self, mock_archive_service, dbsession, mock_configuration
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "report_details_files_array": "general_access",
                        "commit_report": "general_access",
                    },
                }
            }
        )
        commit = CommitFactory()
        dbsession.add(commit)
        report_row = CommitReport(commit=commit, code=None)
        dbsession.add(report_row)
        report_details = ReportDetailsFactory(
            report=report_row, report_id=report_row.id_
        )
        dbsession.add(report_details)
        dbsession.flush()

        report_details._files_array = [
            {
                "filename": "test_file_1.py",
                "file_index": 2,
                "file_totals": [1, 10, 8, 2, 5, "80.00000", 6, 7, 9, 8, 20, 40, 13],
                "diff_totals": [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            },
            {
                "filename": "test_file_2.py",
                "file_index": 0,
                "file_totals": [1, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
        ]
        report_details._files_array_storage_path = None
        assert (
            dbsession.query(ReportDetails).filter_by(report_id=report_row.id_).first()
            is not None
        )

        task = BackfillCommitDataToStorageTask()
        result = task.handle_single_report_row(dbsession, commit, report_row)
        assert result == {"success": True, "errors": []}
        assert report_details._files_array is None
        assert report_details._files_array_storage_path is not None
        mock_archive_service.return_value.write_json_data_to_storage.assert_called()

    @patch("database.utils.ArchiveService")
    def test_handle_single_report_row_ReportDetails_missing_data(
        self, mock_archive_service, dbsession
    ):
        commit = CommitFactory()
        dbsession.add(commit)
        report_row = CommitReport(commit=commit, code=None)
        dbsession.add(report_row)
        report_details = ReportDetailsFactory(
            report=report_row, report_id=report_row.id_
        )
        dbsession.add(report_details)
        dbsession.flush()

        report_details._files_array = None
        report_details._files_array_storage_path = None
        assert (
            dbsession.query(ReportDetails).filter_by(report_id=report_row.id_).first()
            is not None
        )

        task = BackfillCommitDataToStorageTask()
        result = task.handle_single_report_row(dbsession, commit, report_row)
        assert result == {"success": False, "errors": ["missing_data"]}
        assert report_details._files_array is None
        assert report_details._files_array_storage_path is None
        mock_archive_service.return_value.write_json_data_to_storage.assert_not_called()

    @patch("tasks.backfill_commit_data_to_storage.ReportService.save_report")
    @patch(
        "tasks.backfill_commit_data_to_storage.ReportService.get_existing_report_for_commit",
        return_value="the existing report",
    )
    def test_handle_single_report_row_create_ReportDetails(
        self, mock_get_existing_report, mock_save_report, dbsession, mock_configuration
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "report_details_files_array": "general_access",
                        "commit_report": "general_access",
                    },
                }
            }
        )

        commit = CommitFactory()
        dbsession.add(commit)
        report_row = CommitReport(commit=commit, code=None)
        dbsession.add(report_row)
        dbsession.flush()

        def mock_save_report_side_effect(received_commit, actual_report):
            assert received_commit == commit
            assert actual_report == "the existing report"
            commit.report.details._files_array_storage_path = "path/to/storage"
            commit.report.details._files_array = None

        mock_save_report.side_effect = mock_save_report_side_effect

        assert (
            dbsession.query(ReportDetails).filter_by(report_id=report_row.id_).first()
            is None
        )

        task = BackfillCommitDataToStorageTask()
        result = task.handle_single_report_row(dbsession, commit, report_row)
        assert result == {"success": True, "errors": []}
        report_details = (
            dbsession.query(ReportDetails).filter_by(report_id=report_row.id_).first()
        )
        assert report_details is not None
        assert isinstance(report_details, ReportDetails)
        assert report_details._files_array is None
        assert report_details._files_array_storage_path == "path/to/storage"
        mock_get_existing_report.assert_called_with(commit, report_code=None)
        mock_save_report.assert_called_with(commit, "the existing report")

    @patch(
        "tasks.backfill_commit_data_to_storage.BackfillCommitDataToStorageTask.handle_report_json"
    )
    @patch(
        "tasks.backfill_commit_data_to_storage.BackfillCommitDataToStorageTask.handle_all_report_rows"
    )
    def test_run(self, mock_handle_all_report_rows, mock_handle_report_json, dbsession):
        commit = CommitFactory()
        dbsession.add(commit)
        dbsession.flush()

        mock_handle_all_report_rows.return_value = {"success": True, "errors": []}
        mock_handle_report_json.return_value = {
            "success": False,
            "errors": [BackfillError.missing_data.value],
        }

        assert dbsession.query(Commit).get(commit.id_) is not None
        task = BackfillCommitDataToStorageTask()
        result = task.run_impl(dbsession, commitid=commit.id_)
        assert result == {"success": False, "errors": ["missing_data"]}

    @patch(
        "tasks.backfill_commit_data_to_storage.BackfillCommitDataToStorageTask.handle_report_json"
    )
    @patch(
        "tasks.backfill_commit_data_to_storage.BackfillCommitDataToStorageTask.handle_all_report_rows"
    )
    def test_run_missing_commit(
        self, mock_handle_all_report_rows, mock_handle_report_json, dbsession
    ):
        mock_handle_all_report_rows.return_value = {"success": True, "errors": []}
        mock_handle_report_json.return_value = {
            "success": False,
            "errors": [BackfillError.missing_data.value],
        }

        assert dbsession.query(Commit).get(-1) is None
        task = BackfillCommitDataToStorageTask()
        result = task.run_impl(dbsession, commitid=-1)
        assert result == {"success": False, "errors": ["commit_not_found"]}
