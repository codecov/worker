import json

from celery import group
from shared.reports.readonly import ReadOnlyReport
from shared.reports.resources import Report
from shared.reports.types import ReportTotals
from shared.torngit.exceptions import TorngitRateLimitError
from shared.yaml import UserYaml

from database.enums import CompareCommitError, CompareCommitState
from database.models import CompareComponent, CompareFlag, RepositoryFlag
from database.tests.factories import CompareCommitFactory
from rollouts import PARALLEL_COMPONENT_COMPARISON
from services.report import ReportService
from tasks.compute_comparison import ComputeComparisonTask


class TestComputeComparisonTask(object):
    def test_set_state_to_processed(
        self, dbsession, mocker, mock_repo_provider, mock_storage
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
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
        get_current_yaml = mocker.patch("tasks.compute_comparison.get_current_yaml")
        get_current_yaml.return_value = UserYaml({"coverage": {"status": None}})

        task.run_impl(dbsession, comparison.id)
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

    def test_set_state_to_processed_non_empty_report_with_flag_comparisons(
        self,
        dbsession,
        mocker,
        mock_repo_provider,
        mock_storage,
        sample_report_with_multiple_flags,
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(
                sample_report_with_multiple_flags
            ),
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
        get_current_yaml = mocker.patch("tasks.compute_comparison.get_current_yaml")
        get_current_yaml.return_value = UserYaml({"coverage": {"status": None}})

        unit_repositoryflag = RepositoryFlag(
            repository_id=comparison.compare_commit.repository.repoid, flag_name="unit"
        )
        dbsession.add(unit_repositoryflag)
        task.run_impl(dbsession, comparison.id)
        dbsession.flush()
        assert comparison.state == CompareCommitState.processed.value
        compare_flag_records = dbsession.query(CompareFlag).all()
        assert len(compare_flag_records) == 2
        assert compare_flag_records[0].repositoryflag_id == unit_repositoryflag.id_

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

    def test_flag_comparisons_without_head_report(
        self,
        dbsession,
        mocker,
        mock_repo_provider,
        mock_storage,
        sample_report_without_flags,
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report_without_flags),
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
        get_current_yaml = mocker.patch("tasks.compute_comparison.get_current_yaml")
        get_current_yaml.return_value = UserYaml({"coverage": {"status": None}})

        task.run_impl(dbsession, comparison.id)
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

    def test_update_existing_flag_comparisons(
        self, dbsession, mocker, mock_repo_provider, mock_storage, sample_report
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
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
        get_current_yaml = mocker.patch("tasks.compute_comparison.get_current_yaml")
        get_current_yaml.return_value = UserYaml({"coverage": {"status": None}})

        repositoryflag = RepositoryFlag(
            repository_id=comparison.compare_commit.repository.repoid, flag_name="unit"
        )
        dbsession.add(repositoryflag)
        existing_flag_comparison = CompareFlag(
            commit_comparison=comparison,
            repositoryflag=repositoryflag,
            patch_totals=None,
            head_totals=None,
            base_totals=None,
        )
        dbsession.add(existing_flag_comparison)
        task.run_impl(dbsession, comparison.id)
        dbsession.flush()
        assert comparison.state == CompareCommitState.processed.value
        compare_flag_records = dbsession.query(CompareFlag).all()
        assert len(compare_flag_records) == 1
        assert compare_flag_records[0].repositoryflag_id == repositoryflag.id_
        assert compare_flag_records[0].patch_totals is not None

    def test_set_state_to_error_missing_base_report(
        self, dbsession, mocker, sample_report
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        comparison = CompareCommitFactory.create()
        # We need a head report, but no base report
        head_commit = comparison.compare_commit
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            side_effect=lambda commit,
            *args,
            **kwargs: ReadOnlyReport.create_from_report(sample_report)
            if commit == head_commit
            else None,
        )
        patch_totals = ReportTotals(
            files=3, lines=200, hits=100, misses=100, coverage="10.5"
        )
        mocker.patch(
            "tasks.compute_comparison.ComparisonProxy.get_patch_totals",
            return_value=patch_totals,
        )
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        result = task.run_impl(dbsession, comparison.id)
        dbsession.flush()
        assert result == {"successful": False, "error": "missing_base_report"}
        assert comparison.state == CompareCommitState.error.value
        assert comparison.patch_totals == {
            "hits": 100,
            "misses": 100,
            "partials": 0,
            "coverage": 0.105,
        }
        assert comparison.error == CompareCommitError.missing_base_report.value

    def test_set_state_to_error_missing_head_report(
        self, dbsession, mocker, sample_report
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            side_effect=(ReadOnlyReport.create_from_report(sample_report), None),
        )
        task.run_impl(dbsession, comparison.id)
        dbsession.flush()
        assert comparison.state == CompareCommitState.error.value
        assert comparison.error == CompareCommitError.missing_head_report.value

    def test_run_task_ratelimit_error(self, dbsession, mocker, sample_report):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        patch_totals = ReportTotals(
            files=3, lines=200, hits=100, misses=100, coverage="50.00"
        )
        mocker.patch(
            "tasks.compute_comparison.ComparisonProxy.get_patch_totals",
            return_value=patch_totals,
        )
        mocker.patch(
            "tasks.compute_comparison.ComparisonProxy.get_impacted_files",
            side_effect=TorngitRateLimitError("response_data", "message", "reset"),
        )
        task = ComputeComparisonTask()
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(sample_report),
        )
        res = task.run_impl(dbsession, comparison.id)
        assert res == {"successful": False, "error": "torngit_rate_limit"}
        dbsession.flush()
        assert comparison.state == CompareCommitState.error.value
        assert comparison.patch_totals == {
            "hits": 100,
            "misses": 100,
            "partials": 0,
            "coverage": 0.5,
        }
        assert comparison.error is None

    def test_compute_component_comparisons(
        self, dbsession, mocker, mock_repo_provider, mock_storage, sample_report
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
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
        get_current_yaml = mocker.patch("tasks.compute_comparison.get_current_yaml")
        get_current_yaml.return_value = UserYaml(
            {
                "component_management": {
                    "individual_components": [
                        {"component_id": "go_files", "paths": [r".*\.go"]},
                        {"component_id": "unit_flags", "flag_regexes": [r"unit.*"]},
                    ]
                }
            }
        )

        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()

        task = ComputeComparisonTask()
        res = task.run_impl(dbsession, comparison.id)
        assert res == {"successful": True}

        component_comparisons = (
            dbsession.query(CompareComponent)
            .filter_by(commit_comparison_id=comparison.id)
            .all()
        )
        assert len(component_comparisons) == 2

        go_comparison = component_comparisons[0]
        assert go_comparison.component_id == "go_files"
        assert go_comparison.base_totals == {
            "files": 1,
            "lines": 8,
            "hits": 5,
            "misses": 3,
            "partials": 0,
            "coverage": "62.50000",
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 10,
            "complexity_total": 2,
            "diff": 0,
        }
        assert go_comparison.head_totals == {
            "files": 1,
            "lines": 8,
            "hits": 5,
            "misses": 3,
            "partials": 0,
            "coverage": "62.50000",
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 10,
            "complexity_total": 2,
            "diff": 0,
        }
        assert go_comparison.patch_totals == {
            "files": 0,
            "lines": 0,
            "hits": 0,
            "misses": 0,
            "partials": 0,
            "coverage": None,
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 0,
            "complexity": None,
            "complexity_total": None,
            "diff": 0,
        }

        unit_comparison = component_comparisons[1]
        assert unit_comparison.component_id == "unit_flags"
        assert unit_comparison.base_totals == {
            "files": 2,
            "lines": 10,
            "hits": 10,
            "misses": 0,
            "partials": 0,
            "coverage": "100",
            "branches": 1,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 0,
            "complexity_total": 0,
            "diff": 0,
        }
        assert unit_comparison.head_totals == {
            "files": 2,
            "lines": 10,
            "hits": 10,
            "misses": 0,
            "partials": 0,
            "coverage": "100",
            "branches": 1,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 0,
            "complexity_total": 0,
            "diff": 0,
        }
        assert unit_comparison.patch_totals == {
            "files": 1,
            "lines": 0,
            "hits": 0,
            "misses": 0,
            "partials": 0,
            "coverage": None,
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 0,
            "complexity": None,
            "complexity_total": None,
            "diff": 0,
        }

    def test_compute_component_comparisons_parallel(
        self, dbsession, mocker, mock_repo_provider, mock_storage, sample_report
    ):
        mocker.patch("tasks.base.get_db_session", return_value=dbsession)

        mocker.patch.object(group, "apply_async", group.apply)
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=True
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
        mocker.patch(
            "services.comparison.get_repo_provider_service",
            return_value=mock_repo_provider,
        )
        get_current_yaml = mocker.patch("tasks.compute_comparison.get_current_yaml")
        get_current_yaml.return_value = UserYaml(
            {
                "component_management": {
                    "individual_components": [
                        {"component_id": "go_files", "paths": [r".*\.go"]},
                        {"component_id": "unit_flags", "flag_regexes": [r"unit.*"]},
                    ]
                }
            }
        )

        get_current_yaml = mocker.patch(
            "tasks.compute_component_comparison.get_current_yaml"
        )
        get_current_yaml.return_value = UserYaml(
            {
                "component_management": {
                    "individual_components": [
                        {"component_id": "go_files", "paths": [r".*\.go"]},
                        {"component_id": "unit_flags", "flag_regexes": [r"unit.*"]},
                    ]
                }
            }
        )

        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        comparison_id = comparison.id

        task = ComputeComparisonTask()
        res = task.run_impl(dbsession, comparison.id)
        assert res == {"successful": True}

        component_comparisons = (
            dbsession.query(CompareComponent)
            .filter_by(commit_comparison_id=comparison_id)
            .all()
        )
        assert len(component_comparisons) == 2

        go_comparison = component_comparisons[0]
        assert go_comparison.component_id == "go_files"
        assert go_comparison.base_totals == {
            "files": 1,
            "lines": 8,
            "hits": 5,
            "misses": 3,
            "partials": 0,
            "coverage": "62.50000",
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 10,
            "complexity_total": 2,
            "diff": 0,
        }
        assert go_comparison.head_totals == {
            "files": 1,
            "lines": 8,
            "hits": 5,
            "misses": 3,
            "partials": 0,
            "coverage": "62.50000",
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 10,
            "complexity_total": 2,
            "diff": 0,
        }
        assert go_comparison.patch_totals == {
            "files": 0,
            "lines": 0,
            "hits": 0,
            "misses": 0,
            "partials": 0,
            "coverage": None,
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 0,
            "complexity": None,
            "complexity_total": None,
            "diff": 0,
        }

        unit_comparison = component_comparisons[1]
        assert unit_comparison.component_id == "unit_flags"
        assert unit_comparison.base_totals == {
            "files": 2,
            "lines": 10,
            "hits": 10,
            "misses": 0,
            "partials": 0,
            "coverage": "100",
            "branches": 1,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 0,
            "complexity_total": 0,
            "diff": 0,
        }
        assert unit_comparison.head_totals == {
            "files": 2,
            "lines": 10,
            "hits": 10,
            "misses": 0,
            "partials": 0,
            "coverage": "100",
            "branches": 1,
            "methods": 0,
            "messages": 0,
            "sessions": 1,
            "complexity": 0,
            "complexity_total": 0,
            "diff": 0,
        }
        assert unit_comparison.patch_totals == {
            "files": 1,
            "lines": 0,
            "hits": 0,
            "misses": 0,
            "partials": 0,
            "coverage": None,
            "branches": 0,
            "methods": 0,
            "messages": 0,
            "sessions": 0,
            "complexity": None,
            "complexity_total": None,
            "diff": 0,
        }

    def test_compute_component_comparisons_empty_diff(
        self,
        dbsession,
        mocker,
        mock_repo_provider,
        mock_storage,
        sample_report_with_multiple_flags,
    ):
        mocker.patch.object(
            PARALLEL_COMPONENT_COMPARISON, "check_value", return_value=False
        )
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=ReadOnlyReport.create_from_report(
                sample_report_with_multiple_flags
            ),
        )
        mock_repo_provider.get_compare.return_value = {"diff": {"files": {}}}

        get_current_yaml = mocker.patch("tasks.compute_comparison.get_current_yaml")
        get_current_yaml.return_value = UserYaml(
            {
                "component_management": {
                    "individual_components": [
                        {"component_id": "go_files", "paths": [r".*\.go"]},
                        {"component_id": "unit_flags", "flag_regexes": [r"unit.*"]},
                    ]
                }
            }
        )

        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()

        task = ComputeComparisonTask()
        res = task.run_impl(dbsession, comparison.id)
        assert res == {"successful": True}

        component_comparisons = (
            dbsession.query(CompareComponent)
            .filter_by(commit_comparison_id=comparison.id)
            .all()
        )
        assert len(component_comparisons) == 2
        for comparison in component_comparisons:
            assert comparison.patch_totals is None

        flag_comparisons = dbsession.query(CompareFlag).all()
        assert len(flag_comparisons) == 2
        for comparison in flag_comparisons:
            assert comparison.patch_totals is None
