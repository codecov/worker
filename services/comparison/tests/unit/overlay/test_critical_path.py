import json
from datetime import datetime

from database.tests.factories.profiling import ProfilingCommitFactory
from services.comparison.overlays.critical_path import (
    CriticalPathOverlay,
    ProfilingSummaryDataAnalyzer,
    _load_critical_path_report,
)


def test_load_critical_path_report(
    mock_configuration, dbsession, mock_storage, sample_comparison
):
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    data = {
        "version": "v1",
        "general": {"total_profiled_files": 10},
        "file_groups": {
            "sum_of_executions": {
                "top_10_percent": ["efg.py"],
                "above_1_stdev": ["efg.py"],
            },
            "max_number_of_executions": {"above_1_stdev": []},
            "avg_number_of_executions": {"above_1_stdev": []},
        },
    }
    url = "v4/banana/abcdef.json"
    mock_storage.write_file("bucket", url, json.dumps(data))
    pc = ProfilingCommitFactory.create(
        summarized_location=url, repository=sample_comparison.base.commit.repository
    )
    dbsession.add(pc)
    dbsession.flush()
    res = _load_critical_path_report(sample_comparison)
    assert isinstance(res, ProfilingSummaryDataAnalyzer)
    assert res.get_critical_files_filenames() == ["efg.py"]


def test_load_critical_path_report_not_summarized(
    mock_configuration, dbsession, mock_storage, sample_comparison
):
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    data = {
        "version": "v1",
        "general": {"total_profiled_files": 10},
        "file_groups": {
            "sum_of_executions": {
                "top_10_percent": ["efg.py"],
                "above_1_stdev": ["efg.py"],
            },
            "max_number_of_executions": {"above_1_stdev": []},
            "avg_number_of_executions": {"above_1_stdev": []},
        },
    }
    url = "v4/banana/abcdef.json"
    mock_storage.write_file("bucket", url, json.dumps(data))
    pc = ProfilingCommitFactory.create(
        summarized_location=None,
        repository=sample_comparison.base.commit.repository,
        last_summarized_at=datetime(2021, 3, 1, 5),
    )
    second_pc = ProfilingCommitFactory.create(
        summarized_location=url,
        repository=sample_comparison.base.commit.repository,
        last_summarized_at=datetime(2021, 3, 1, 4),
    )
    dbsession.add(pc)
    dbsession.add(second_pc)
    dbsession.flush()
    res = _load_critical_path_report(sample_comparison)
    assert isinstance(res, ProfilingSummaryDataAnalyzer)
    assert res.get_critical_files_filenames() == ["efg.py"]


def test_load_critical_path_report_no_commit(sample_comparison):
    res = _load_critical_path_report(sample_comparison)
    assert res is None


def test_load_critical_path_report_yes_commit_no_storage(
    mock_configuration, dbsession, mock_storage, sample_comparison
):
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    url = "v4/banana/abcdef.json"
    pc = ProfilingCommitFactory.create(
        summarized_location=url, repoid=sample_comparison.base.commit.repoid
    )
    dbsession.add(pc)
    dbsession.flush()
    assert _load_critical_path_report(sample_comparison) is None


class TestCriticalPathOverlay(object):
    def test_search_files_for_critical_changes_none_report(self, sample_comparison):
        a = CriticalPathOverlay(sample_comparison, None)
        assert a.search_files_for_critical_changes(["filenames", "to", "search"]) == []
