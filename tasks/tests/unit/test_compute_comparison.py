import json

import pytest
from shared.reports.readonly import ReadOnlyReport
from shared.reports.resources import Report
from shared.torngit.exceptions import TorngitRateLimitError

from database.enums import CompareCommitError, CompareCommitState
from database.tests.factories import CompareCommitFactory
from services.report import ReportService
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
        mocker.patch.object(
            ReadOnlyReport, "should_load_rust_version", return_value=True
        )
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(Report()),
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
        assert comparison.state == CompareCommitState.processed.value
        data_in_storage = mock_storage.read_file(
            "archive", comparison.report_storage_path
        )
        assert comparison.patch_totals == {
            "hits": 0,
            "misses": 0,
            "partials": 0,
            "coverage": None,
        }
        assert json.loads(data_in_storage) == {
            "files": [],
            "changes_summary": {
                "patch_totals": {
                    "hits": 0,
                    "misses": 0,
                    "partials": 0,
                    "coverage": None,
                }
            },
        }

    @pytest.mark.asyncio
    async def test_set_state_to_processed_non_empty_report(
        self, dbsession, mocker, mock_repo_provider, mock_storage, sample_report
    ):
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReadOnlyReport, "should_load_rust_version", return_value=True
        )
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
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
        assert comparison.state == CompareCommitState.processed.value
        data_in_storage = mock_storage.read_file(
            "archive", comparison.report_storage_path
        )
        assert json.loads(data_in_storage) == {
            "files": [
                {
                    "base_name": "file_2.py",
                    "head_name": "file_2.py",
                    "file_was_added_by_diff": False,
                    "file_was_removed_by_diff": False,
                    "base_coverage": {
                        "hits": 1,
                        "misses": 0,
                        "partials": 1,
                        "branches": 1,
                        "sessions": 0,
                        "complexity": 0,
                        "complexity_total": 0,
                        "methods": 0,
                    },
                    "head_coverage": {
                        "hits": 1,
                        "misses": 0,
                        "partials": 1,
                        "branches": 1,
                        "sessions": 0,
                        "complexity": 0,
                        "complexity_total": 0,
                        "methods": 0,
                    },
                    "removed_diff_coverage": [],
                    "added_diff_coverage": [],
                    "unexpected_line_changes": [
                        [[12, "h"], [11, None]],
                        [[13, None], [12, "h"]],
                        [[51, "p"], [50, None]],
                        [[52, None], [51, "p"]],
                    ],
                    "lines_only_on_base": [2, 3],
                    "lines_only_on_head": [2],
                }
            ],
            "changes_summary": {
                "patch_totals": {
                    "hits": 0,
                    "misses": 0,
                    "partials": 0,
                    "coverage": None,
                }
            },
        }

    @pytest.mark.asyncio
    async def test_set_state_to_error_missing_base_report(self, dbsession, mocker):
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReadOnlyReport, "should_load_rust_version", return_value=True
        )
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=None
        )
        await task.run_async(dbsession, comparison.id)
        dbsession.flush()
        assert comparison.state == CompareCommitState.error.value
        assert comparison.error == CompareCommitError.missing_base_report.value

    @pytest.mark.asyncio
    async def test_set_state_to_error_missing_head_report(
        self, dbsession, mocker, sample_report
    ):
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReadOnlyReport, "should_load_rust_version", return_value=True
        )
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            side_effect=(ReadOnlyReport.create_from_report(sample_report), None),
        )
        await task.run_async(dbsession, comparison.id)
        dbsession.flush()
        assert comparison.state == CompareCommitState.error.value
        assert comparison.error == CompareCommitError.missing_head_report.value

    @pytest.mark.asyncio
    async def test_run_task_ratelimit_error(self, dbsession, mocker, sample_report):
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        mocker.patch.object(
            ComputeComparisonTask,
            "serialize_impacted_files",
            side_effect=TorngitRateLimitError("response_data", "message", "reset"),
        )
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
        )
        res = await task.run_async(dbsession, comparison.id)
        assert res == {"successful": False}
        dbsession.flush()
        assert comparison.state == CompareCommitState.pending.value
        assert comparison.error is None
