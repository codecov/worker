import json
import pytest

from database.enums import CompareCommitState
from services.report import ReportService
from shared.reports.resources import Report
from database.tests.factories import CompareCommitFactory
from tasks.compute_comparison import ComputeComparisonTask


class TestComputeComparisonTask(object):
    @pytest.mark.asyncio
    async def test_set_state_to_processed(
        self, dbsession, mocker, mock_repo_provider, mock_storage
    ):
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocked_get_current_yaml = mocker.patch(
            "tasks.compute_comparison.get_current_yaml",
        )
        mocked_get_current_yaml.return_value = {}
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=Report()
        )
        await task.run_async(dbsession, comparison.id)
        dbsession.flush()
        assert comparison.state is CompareCommitState.processed
        data_in_storage = mock_storage.read_file(
            "archive", comparison.report_storage_path
        )
        assert json.loads(data_in_storage) == {"changes": [], "diff": []}

    @pytest.mark.asyncio
    async def test_set_state_to_processed_non_empty_report(
        self, dbsession, mocker, mock_repo_provider, mock_storage, sample_report
    ):
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocked_get_current_yaml = mocker.patch(
            "tasks.compute_comparison.get_current_yaml",
        )
        mocked_get_current_yaml.return_value = {}
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=sample_report
        )
        mock_repo_provider.get_compare.return_value = {
            "diff": {
                "files": {
                    "file_2.py": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {"header": ["2", "5", "2", "5"], "lines": ["+", "-", "-"]}
                        ],
                    }
                }
            }
        }
        await task.run_async(dbsession, comparison.id)
        dbsession.flush()
        assert comparison.state is CompareCommitState.processed
        data_in_storage = mock_storage.read_file(
            "archive", comparison.report_storage_path
        )
        assert json.loads(data_in_storage) == {
            "changes": [
                {
                    "path": "file_2.py",
                    "base_totals": [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                    "compare_totals": [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                    "patch": None,
                    "new": False,
                    "deleted": False,
                    "in_diff": True,
                    "old_path": None,
                }
            ],
            "diff": [
                {
                    "path": "file_2.py",
                    "base_totals": [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                    "compare_totals": [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                    "patch": [0, 0, 0, 0, 0, None, 0, 0, 0, 0, 0, 0, 0],
                    "new": False,
                    "deleted": False,
                    "in_diff": True,
                    "old_path": None,
                }
            ],
        }
