import json
import pytest

from tasks.compute_comparison import ComputeComparisonTask
from database.tests.factories import CompareCommitFactory
from database.enums import CompareCommitState
from services.report import ReportService
from shared.reports.resources import Report


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


    async def test_set_state_to_processed_non_empty report(
        self, dbsession, mocker, mock_repo_provider, mock_storage, sample_comparison
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

