import json
from datetime import datetime

import pytest

from database.tests.factories.profiling import ProfilingCommitFactory
from services.comparison.overlays.critical_path import (
    CriticalPathOverlay,
    ProfilingSummaryDataAnalyzer,
    _load_critical_path_report,
    _load_full_profiling_analyzer,
)


@pytest.fixture
def sample_open_telemetry_collected_as_str():
    return json.dumps(
        {
            "files": [],
            "groups": [
                {
                    "count": 3,
                    "files": [
                        {
                            "filename": "file_1.go",
                            "ln_ex_ct": [
                                [3, 3],
                                [4, 3],
                                [5, 3],
                                [21, 3],
                                [22, 3],
                                [26, 3],
                            ],
                        }
                    ],
                    "group_name": "run/app.tasks.upload.Upload",
                },
                {
                    "count": 2,
                    "files": [
                        {
                            "filename": "database/base.py",
                            "ln_ex_ct": [[17, 2], [32, 2]],
                        },
                        {
                            "filename": "database/engine.py",
                            "ln_ex_ct": [[18, 2], [19, 2], [24, 2]],
                        },
                    ],
                    "group_name": "run/app.tasks.upload_processor.UploadProcessorTask",
                },
            ],
            "metadata": {"version": "v1"},
        }
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
        summarized_location=url,
        repository=sample_comparison.project_coverage_base.commit.repository,
        last_summarized_at=datetime(2021, 10, 10),
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
        repository=sample_comparison.project_coverage_base.commit.repository,
        last_summarized_at=datetime(2021, 3, 1, 5),
    )
    second_pc = ProfilingCommitFactory.create(
        summarized_location=url,
        repository=sample_comparison.project_coverage_base.commit.repository,
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
    assert _load_full_profiling_analyzer(sample_comparison) is None


def test_load_critical_path_report_yes_commit_no_storage(
    mock_configuration, dbsession, mock_storage, sample_comparison
):
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    url = "v4/banana/abcdef.json"
    pc = ProfilingCommitFactory.create(
        summarized_location=url,
        repository=sample_comparison.project_coverage_base.commit.repository,
        last_summarized_at=datetime(2021, 3, 1, 5),
    )
    dbsession.add(pc)
    dbsession.flush()
    assert _load_critical_path_report(sample_comparison) is None
    assert _load_full_profiling_analyzer(sample_comparison) is None


def test_critical_files_from_yaml_no_paths(mocker, sample_comparison):
    sample_comparison.comparison.current_yaml = dict()
    mocked_get_yaml = mocker.patch(
        "services.comparison.overlays.critical_path.get_current_yaml"
    )
    overlay = CriticalPathOverlay(sample_comparison, None)
    critical_paths_from_yaml = overlay._get_critical_files_from_yaml(
        ["batata.txt", "a.py"]
    )
    assert critical_paths_from_yaml == []
    mocked_get_yaml.assert_not_called()


def test_critical_files_from_yaml_with_paths(mocker, sample_comparison):
    sample_comparison.comparison.current_yaml = {
        "profiling": {
            "critical_files_paths": ["src/critical", "important.txt"],
        }
    }
    mocked_get_yaml = mocker.patch(
        "services.comparison.overlays.critical_path.get_current_yaml"
    )
    overlay = CriticalPathOverlay(sample_comparison, None)
    critical_paths_from_yaml = overlay._get_critical_files_from_yaml(
        ["batata.txt", "src/critical/a.py"]
    )
    assert critical_paths_from_yaml == ["src/critical/a.py"]
    mocked_get_yaml.assert_not_called()


def test_critical_files_from_yaml_with_paths_get_yaml_from_provider(
    mocker, sample_comparison
):
    mocked_get_yaml = mocker.patch(
        "services.comparison.overlays.critical_path.get_current_yaml",
        return_value={
            "profiling": {
                "critical_files_paths": ["src/critical", "important.txt"],
            }
        },
    )
    overlay = CriticalPathOverlay(sample_comparison, None)
    critical_paths_from_yaml = overlay._get_critical_files_from_yaml(
        ["batata.txt", "src/critical/a.py"]
    )
    assert critical_paths_from_yaml == ["src/critical/a.py"]
    mocked_get_yaml.assert_called()


class TestCriticalPathOverlay(object):
    def test_search_files_for_critical_changes_none_report(self, sample_comparison):
        sample_comparison.comparison.current_yaml = dict()
        a = CriticalPathOverlay(sample_comparison, None)
        assert a.search_files_for_critical_changes(["filenames", "to", "search"]) == []

    def test_search_files_for_critical_changes_none_report_with_yaml_path(
        self, sample_comparison, mocker
    ):
        sample_comparison.comparison.current_yaml = {
            "profiling": {
                "critical_files_paths": ["src/critical", "important.txt"],
            }
        }
        a = CriticalPathOverlay(sample_comparison, None)
        assert a.search_files_for_critical_changes(
            ["filenames", "to", "search", "important.txt"]
        ) == ["important.txt"]

    def test_find_impacted_endpoints_no_analyzer(self, sample_comparison):
        a = CriticalPathOverlay(sample_comparison, None)
        a._profiling_analyzer = None
        a.find_impacted_endpoints() is None

    def test_find_impacted_endpoints(
        self,
        dbsession,
        sample_comparison,
        mock_storage,
        sample_open_telemetry_collected_as_str,
        mock_configuration,
        mock_repo_provider,
    ):
        mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
        url = "v4/banana/abcdef.json"
        pc = ProfilingCommitFactory.create(
            summarized_location="someurl",
            joined_location=url,
            repository=sample_comparison.project_coverage_base.commit.repository,
            last_summarized_at=datetime(2021, 3, 1, 4),
        )
        dbsession.add(pc)
        dbsession.flush()
        mock_repo_provider.get_compare.return_value = {
            "diff": {
                "files": {
                    "file_1.go": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["1", "8", "1", "9"],
                                "lines": [
                                    " Overview",
                                    " --------",
                                    " ",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "+",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    " ",
                                    " .. code-block:: shell-session",
                                    " ",
                                ],
                            },
                            {
                                "header": ["46", "12", "47", "19"],
                                "lines": [
                                    " ",
                                    " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                    " -",
                                ],
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_storage.write_file("bucket", url, sample_open_telemetry_collected_as_str)
        a = CriticalPathOverlay(sample_comparison, None)
        res = a.find_impacted_endpoints()
        assert res == [
            {
                "files": [{"filename": "file_1.go", "impacted_base_lines": [5]}],
                "group_name": "run/app.tasks.upload.Upload",
            }
        ]
