import json

import pytest
from mock import patch
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.reports.types import CoverageDatapoint, LineSession

from database.models.labelanalysis import LabelAnalysisRequest
from database.tests.factories import RepositoryFactory
from database.tests.factories.labelanalysis import LabelAnalysisRequestFactory
from database.tests.factories.staticanalysis import (
    StaticAnalysisSingleFileSnapshotFactory,
    StaticAnalysisSuiteFactory,
    StaticAnalysisSuiteFilepathFactory,
)
from services.report import ReportService
from services.static_analysis import StaticAnalysisComparisonService
from tasks.label_analysis import (
    LabelAnalysisRequestProcessingTask,
    LabelAnalysisRequestState,
)

sample_head_static_analysis_dict = {
    "empty_lines": [2, 3, 11],
    "warnings": [],
    "filename": "source.py",
    "functions": [
        {
            "identifier": "some_function",
            "start_line": 6,
            "end_line": 10,
            "code_hash": "e69c18eff7d24f8bad3370db87f64333",
            "complexity_metrics": {
                "conditions": 1,
                "mccabe_cyclomatic_complexity": 2,
                "returns": 1,
                "max_nested_conditional": 1,
            },
        }
    ],
    "hash": "84d371ab1c57d2349038ac3671428803",
    "language": "python",
    "number_lines": 11,
    "statements": [
        (
            1,
            {
                "line_surety_ancestorship": None,
                "start_column": 0,
                "line_hash": "55c30cf01e202728b6952e9cba304798",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            5,
            {
                "line_surety_ancestorship": None,
                "start_column": 4,
                "line_hash": "1d7be9f2145760a59513a4049fcd0d1c",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            6,
            {
                "line_surety_ancestorship": 5,
                "start_column": 4,
                "line_hash": "f802087a854c26782ee8d4ece7214425",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            7,
            {
                "line_surety_ancestorship": None,
                "start_column": 8,
                "line_hash": "6ae3393fa7880fe8a844c03256cac37b",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            8,
            {
                "line_surety_ancestorship": 6,
                "start_column": 4,
                "line_hash": "5b099d1822e9236c540a5701a657225e",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            9,
            {
                "line_surety_ancestorship": 8,
                "start_column": 4,
                "line_hash": "e5d4915bb7dddeb18f53dc9fde9a3064",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            10,
            {
                "line_surety_ancestorship": 9,
                "start_column": 4,
                "line_hash": "e70ce43136171575ee525375b10f91a1",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
    ],
    "definition_lines": [(4, 6)],
    "import_lines": [],
}

sample_base_static_analysis_dict = {
    "empty_lines": [2, 3, 11],
    "warnings": [],
    "filename": "source.py",
    "functions": [
        {
            "identifier": "some_function",
            "start_line": 6,
            "end_line": 10,
            "code_hash": "e4b52b6da12184142fcd7ff2c8412662",
            "complexity_metrics": {
                "conditions": 1,
                "mccabe_cyclomatic_complexity": 2,
                "returns": 1,
                "max_nested_conditional": 1,
            },
        }
    ],
    "hash": "811d0016249a5b1400a685164e5295de",
    "language": "python",
    "number_lines": 11,
    "statements": [
        (
            1,
            {
                "line_surety_ancestorship": None,
                "start_column": 0,
                "line_hash": "55c30cf01e202728b6952e9cba304798",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            5,
            {
                "line_surety_ancestorship": None,
                "start_column": 4,
                "line_hash": "1d7be9f2145760a59513a4049fcd0d1c",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            6,
            {
                "line_surety_ancestorship": 5,
                "start_column": 4,
                "line_hash": "52f98812dca4687f18373b87433df695",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            7,
            {
                "line_surety_ancestorship": None,
                "start_column": 8,
                "line_hash": "6ae3393fa7880fe8a844c03256cac37b",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            8,
            {
                "line_surety_ancestorship": 7,
                "start_column": 8,
                "line_hash": "5b099d1822e9236c540a5701a657225e",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            9,
            {
                "line_surety_ancestorship": 6,
                "start_column": 4,
                "line_hash": "e5d4915bb7dddeb18f53dc9fde9a3064",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            10,
            {
                "line_surety_ancestorship": 9,
                "start_column": 4,
                "line_hash": "e70ce43136171575ee525375b10f91a1",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
    ],
    "definition_lines": [(4, 6)],
    "import_lines": [],
}


@pytest.fixture
def sample_report_with_labels():
    r = Report()
    first_rf = ReportFile("source.py")
    first_rf.append(
        5,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=1,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=1,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["apple", "label_one", "pineapple", "banana"],
                )
            ],
            complexity=None,
        ),
    )
    first_rf.append(
        6,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=1,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=1,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["label_one", "pineapple", "banana"],
                )
            ],
            complexity=None,
        ),
    )
    first_rf.append(
        7,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=1,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=1,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["banana"],
                )
            ],
            complexity=None,
        ),
    )
    first_rf.append(
        8,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=1,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=1,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["banana"],
                ),
                CoverageDatapoint(
                    sessionid=5,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["orangejuice"],
                ),
            ],
            complexity=None,
        ),
    )
    first_rf.append(
        99,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=5,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=5,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["justjuice"],
                ),
            ],
            complexity=None,
        ),
    )
    first_rf.append(
        8,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=1,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=1,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["label_one", "pineapple", "banana"],
                ),
                CoverageDatapoint(
                    sessionid=5,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["Th2dMtk4M_codecov", "applejuice"],
                ),
            ],
            complexity=None,
        ),
    )
    second_rf = ReportFile("path/from/additionsonly.py")
    second_rf.append(
        6,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=1,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=1,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["whatever", "here"],
                )
            ],
            complexity=None,
        ),
    )
    random_rf = ReportFile("path/from/randomfile_no_static_analysis.html")
    random_rf.append(
        1,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[(LineSession(id=1, coverage=1))],
            datapoints=None,
            complexity=None,
        ),
    )
    r.append(first_rf)
    r.append(second_rf)
    r.append(random_rf)

    return r


def test_simple_call_without_requested_labels_then_with_requested_labels(
    dbsession, mock_storage, mocker, sample_report_with_labels, mock_repo_provider
):
    mock_metrics = mocker.patch("tasks.label_analysis.metrics")
    mock_log_simple_metric = mocker.patch("tasks.label_analysis.log_simple_metric")
    mocker.patch.object(
        LabelAnalysisRequestProcessingTask,
        "_get_lines_relevant_to_diff",
        return_value={
            "all": False,
            "files": {"source.py": {"all": False, "lines": {8, 6}}},
        },
    )
    mocker.patch.object(
        ReportService,
        "get_existing_report_for_commit",
        return_value=sample_report_with_labels,
    )
    repository = RepositoryFactory.create()
    larf = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larf)
    dbsession.flush()
    base_sasf = StaticAnalysisSuiteFactory.create(commit=larf.base_commit)
    head_sasf = StaticAnalysisSuiteFactory.create(commit=larf.head_commit)
    dbsession.add(base_sasf)
    dbsession.add(head_sasf)
    dbsession.flush()
    first_path = "abdkasdauchudh.txt"
    second_path = "0diao9u3qdsdu.txt"
    mock_storage.write_file(
        "archive",
        first_path,
        json.dumps(sample_base_static_analysis_dict),
    )
    mock_storage.write_file(
        "archive",
        second_path,
        json.dumps(sample_head_static_analysis_dict),
    )
    first_snapshot = StaticAnalysisSingleFileSnapshotFactory.create(
        repository=repository, content_location=first_path
    )
    second_snapshot = StaticAnalysisSingleFileSnapshotFactory.create(
        repository=repository, content_location=second_path
    )
    dbsession.add(first_snapshot)
    dbsession.add(second_snapshot)
    dbsession.flush()
    first_base_file = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=first_snapshot,
        analysis_suite=base_sasf,
        filepath="source.py",
    )
    first_head_file = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=second_snapshot,
        analysis_suite=head_sasf,
        filepath="source.py",
    )
    dbsession.add(first_base_file)
    dbsession.add(first_head_file)
    dbsession.flush()

    task = LabelAnalysisRequestProcessingTask()
    res = task.run_impl(dbsession, larf.id)
    expected_present_report_labels = [
        "apple",
        "applejuice",
        "banana",
        "here",
        "justjuice",
        "label_one",
        "orangejuice",
        "pineapple",
        "whatever",
    ]
    expected_present_diff_labels = sorted(
        ["applejuice", "banana", "label_one", "orangejuice", "pineapple"]
    )
    expected_result = {
        "absent_labels": [],
        "present_diff_labels": expected_present_diff_labels,
        "present_report_labels": expected_present_report_labels,
        "global_level_labels": ["applejuice", "justjuice", "orangejuice"],
        "success": True,
        "errors": [],
    }
    assert res == expected_result
    mock_metrics.incr.assert_called_with("label_analysis_task.success")
    mock_log_simple_metric.assert_any_call("label_analysis.tests_saved_count", 9)
    mock_log_simple_metric.assert_any_call(
        "label_analysis.requests_with_requested_labels", 0.0
    )
    mock_log_simple_metric.assert_any_call("label_analysis.tests_to_run_count", 6)
    dbsession.flush()
    dbsession.refresh(larf)
    assert larf.state_id == LabelAnalysisRequestState.FINISHED.db_id
    assert larf.result == {
        "absent_labels": [],
        "present_diff_labels": expected_present_diff_labels,
        "present_report_labels": expected_present_report_labels,
        "global_level_labels": ["applejuice", "justjuice", "orangejuice"],
    }
    # Now we call the task again, this time with the requested labels.
    # This illustrates what should happen if we patch the labels after calculating
    # And trigger the task again to save the new results
    larf.requested_labels = ["tangerine", "pear", "banana", "apple"]
    dbsession.flush()
    res = task.run_impl(dbsession, larf.id)
    expected_present_diff_labels = ["banana"]
    expected_present_report_labels = ["apple", "banana"]
    expected_absent_labels = ["pear", "tangerine"]
    assert res == {
        "absent_labels": expected_absent_labels,
        "present_diff_labels": expected_present_diff_labels,
        "present_report_labels": expected_present_report_labels,
        "success": True,
        "global_level_labels": [],
        "errors": [],
    }
    assert larf.result == {
        "absent_labels": expected_absent_labels,
        "present_diff_labels": expected_present_diff_labels,
        "present_report_labels": expected_present_report_labels,
        "global_level_labels": [],
    }
    mock_metrics.incr.assert_called_with(
        "label_analysis_task.already_calculated.new_result"
    )
    mock_log_simple_metric.assert_any_call("label_analysis.tests_saved_count", 9)
    mock_log_simple_metric.assert_any_call(
        "label_analysis.requests_with_requested_labels", 1.0
    )
    mock_log_simple_metric.assert_any_call("label_analysis.requested_labels_count", 4)
    mock_log_simple_metric.assert_any_call("label_analysis.tests_to_run_count", 3)


def test_simple_call_with_requested_labels(
    dbsession, mock_storage, mocker, sample_report_with_labels, mock_repo_provider
):
    mock_metrics = mocker.patch("tasks.label_analysis.metrics")
    mock_log_simple_metric = mocker.patch("tasks.label_analysis.log_simple_metric")
    mocker.patch.object(
        LabelAnalysisRequestProcessingTask,
        "_get_lines_relevant_to_diff",
        return_value={
            "all": False,
            "files": {"source.py": {"all": False, "lines": {8, 6}}},
        },
    )
    mocker.patch.object(
        ReportService,
        "get_existing_report_for_commit",
        return_value=sample_report_with_labels,
    )
    larf = LabelAnalysisRequestFactory.create(
        requested_labels=["tangerine", "pear", "banana", "apple"]
    )
    dbsession.add(larf)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    res = task.run_impl(dbsession, larf.id)
    expected_present_diff_labels = ["banana"]
    expected_present_report_labels = ["apple", "banana"]
    expected_absent_labels = ["pear", "tangerine"]
    assert res == {
        "absent_labels": expected_absent_labels,
        "present_diff_labels": expected_present_diff_labels,
        "present_report_labels": expected_present_report_labels,
        "success": True,
        "global_level_labels": [],
        "errors": [],
    }
    dbsession.flush()
    dbsession.refresh(larf)
    assert larf.state_id == LabelAnalysisRequestState.FINISHED.db_id
    assert larf.result == {
        "absent_labels": expected_absent_labels,
        "present_diff_labels": expected_present_diff_labels,
        "present_report_labels": expected_present_report_labels,
        "global_level_labels": [],
    }
    mock_metrics.incr.assert_called_with("label_analysis_task.success")
    mock_log_simple_metric.assert_any_call("label_analysis.tests_saved_count", 9)
    mock_log_simple_metric.assert_any_call(
        "label_analysis.requests_with_requested_labels", 1.0
    )
    mock_log_simple_metric.assert_any_call("label_analysis.tests_to_run_count", 3)


def test_get_requested_labels(dbsession, mocker):
    larf = LabelAnalysisRequestFactory.create(requested_labels=[])

    def side_effect(*args, **kwargs):
        larf.requested_labels = ["tangerine", "pear", "banana", "apple"]

    mock_refresh = mocker.patch.object(dbsession, "refresh", side_effect=side_effect)
    dbsession.add(larf)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    task.dbsession = dbsession
    labels = task._get_requested_labels(larf)
    mock_refresh.assert_called()
    assert labels == ["tangerine", "pear", "banana", "apple"]


def test_call_label_analysis_no_request_object(dbsession, mocker):
    task = LabelAnalysisRequestProcessingTask()
    mock_metrics = mocker.patch("tasks.label_analysis.metrics")
    res = task.run_impl(db_session=dbsession, request_id=-1)
    assert res == {
        "success": False,
        "present_report_labels": [],
        "present_diff_labels": [],
        "absent_labels": [],
        "global_level_labels": [],
        "errors": [
            {
                "error_code": "not found",
                "error_params": {
                    "extra": {},
                    "message": "LabelAnalysisRequest not found",
                },
            }
        ],
    }
    mock_metrics.incr.assert_called_with(
        "label_analysis_task.failed_to_calculate.larq_not_found"
    )


def test_get_executable_lines_labels_all_labels(sample_report_with_labels):
    executable_lines = {"all": True}
    task = LabelAnalysisRequestProcessingTask()
    assert task.get_executable_lines_labels(
        sample_report_with_labels, executable_lines
    ) == (
        {
            "banana",
            "justjuice",
            "here",
            "pineapple",
            "applejuice",
            "apple",
            "whatever",
            "label_one",
            "orangejuice",
        },
        set(),
    )
    assert task.get_executable_lines_labels(
        sample_report_with_labels, executable_lines
    ) == (task.get_all_report_labels(sample_report_with_labels), set())


def test_get_executable_lines_labels_all_labels_in_one_file(sample_report_with_labels):
    executable_lines = {"all": False, "files": {"source.py": {"all": True}}}
    task = LabelAnalysisRequestProcessingTask()
    assert task.get_executable_lines_labels(
        sample_report_with_labels, executable_lines
    ) == (
        {
            "apple",
            "justjuice",
            "applejuice",
            "label_one",
            "banana",
            "orangejuice",
            "pineapple",
        },
        {"orangejuice", "justjuice", "applejuice"},
    )


def test_get_executable_lines_labels_some_labels_in_one_file(sample_report_with_labels):
    executable_lines = {
        "all": False,
        "files": {"source.py": {"all": False, "lines": set([5, 6])}},
    }
    task = LabelAnalysisRequestProcessingTask()
    assert task.get_executable_lines_labels(
        sample_report_with_labels, executable_lines
    ) == (
        {"apple", "label_one", "pineapple", "banana"},
        set(),
    )


def test_get_executable_lines_labels_some_labels_in_one_file_with_globals(
    sample_report_with_labels,
):
    executable_lines = {
        "all": False,
        "files": {"source.py": {"all": False, "lines": set([6, 8])}},
    }
    task = LabelAnalysisRequestProcessingTask()
    assert task.get_executable_lines_labels(
        sample_report_with_labels, executable_lines
    ) == (
        {"label_one", "pineapple", "banana", "orangejuice", "applejuice"},
        {"applejuice", "justjuice", "orangejuice"},
    )


def test_get_executable_lines_labels_some_labels_in_one_file_other_null(
    sample_report_with_labels,
):
    executable_lines = {
        "all": False,
        "files": {
            "source.py": {"all": False, "lines": set([5, 6])},
            "path/from/randomfile_no_static_analysis.html": None,
        },
    }
    task = LabelAnalysisRequestProcessingTask()
    assert task.get_executable_lines_labels(
        sample_report_with_labels, executable_lines
    ) == (
        {"apple", "label_one", "pineapple", "banana"},
        set(),
    )


def test_get_all_labels_one_session(sample_report_with_labels):
    task = LabelAnalysisRequestProcessingTask()
    assert task.get_labels_per_session(sample_report_with_labels, 1) == {
        "apple",
        "banana",
        "here",
        "label_one",
        "pineapple",
        "whatever",
    }
    assert task.get_labels_per_session(sample_report_with_labels, 2) == set()
    assert task.get_labels_per_session(sample_report_with_labels, 5) == {
        "orangejuice",
        "justjuice",
        "applejuice",
    }


def test_get_relevant_executable_lines_nothing_found(dbsession, mocker):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    larf = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larf)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    task.errors = []
    task.dbsession = dbsession
    parsed_git_diff = []
    assert task.get_relevant_executable_lines(larf, parsed_git_diff) is None


def test_get_relevant_executable_lines_with_static_analyses(dbsession, mocker):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    larf = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larf)
    dbsession.flush()
    base_sasf = StaticAnalysisSuiteFactory.create(commit=larf.base_commit)
    head_sasf = StaticAnalysisSuiteFactory.create(commit=larf.head_commit)
    dbsession.add(base_sasf)
    dbsession.add(head_sasf)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    parsed_git_diff = []
    mocked_res = mocker.patch.object(
        StaticAnalysisComparisonService, "get_base_lines_relevant_to_change"
    )
    assert (
        task.get_relevant_executable_lines(larf, parsed_git_diff)
        == mocked_res.return_value
    )


def test_run_impl_with_error(
    dbsession, mock_storage, mocker, sample_report_with_labels, mock_repo_provider
):
    mock_metrics = mocker.patch("tasks.label_analysis.metrics")
    mocker.patch.object(
        LabelAnalysisRequestProcessingTask,
        "_get_lines_relevant_to_diff",
        side_effect=Exception("Oh no"),
    )
    larf = LabelAnalysisRequestFactory.create(
        requested_labels=["tangerine", "pear", "banana", "apple"]
    )
    dbsession.add(larf)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    res = task.run_impl(dbsession, larf.id)
    expected_result = {
        "absent_labels": [],
        "present_diff_labels": [],
        "present_report_labels": [],
        "success": False,
        "global_level_labels": [],
        "errors": [
            {
                "error_code": "failed",
                "error_params": {"extra": {}, "message": "Failed to calculate"},
            }
        ],
    }
    assert res == expected_result
    dbsession.flush()
    dbsession.refresh(larf)
    assert larf.state_id == LabelAnalysisRequestState.ERROR.db_id
    assert larf.result is None
    mock_metrics.incr.assert_called_with(
        "label_analysis_task.failed_to_calculate.exception"
    )


def test_calculate_result_no_report(
    dbsession, mock_storage, mocker, sample_report_with_labels, mock_repo_provider
):
    mock_metrics = mocker.patch("tasks.label_analysis.metrics")
    larf: LabelAnalysisRequest = LabelAnalysisRequestFactory.create(
        # This being not-ordered is important in the test
        # TO make sure we go through the warning at the bottom of run_impl
        requested_labels=["tangerine", "pear", "banana", "apple"]
    )
    dbsession.add(larf)
    dbsession.flush()
    mocker.patch.object(
        ReportService,
        "get_existing_report_for_commit",
        return_value=None,
    )
    mocker.patch.object(
        LabelAnalysisRequestProcessingTask,
        "_get_lines_relevant_to_diff",
        return_value=(set(), set(), set()),
    )
    task = LabelAnalysisRequestProcessingTask()
    res = task.run_impl(dbsession, larf.id)
    assert res == {
        "success": True,
        "absent_labels": larf.requested_labels,
        "present_diff_labels": [],
        "present_report_labels": [],
        "global_level_labels": [],
        "errors": [
            {
                "error_code": "missing data",
                "error_params": {
                    "extra": {
                        "base_commit": larf.base_commit.commitid,
                        "head_commit": larf.head_commit.commitid,
                    },
                    "message": "Missing base report",
                },
            }
        ],
    }
    mock_metrics.incr.assert_called_with(
        "label_analysis_task.failed_to_calculate.missing_info"
    )


@patch("tasks.label_analysis.parse_git_diff_json", return_value=["parsed_git_diff"])
def test__get_parsed_git_diff(mock_parse_diff, dbsession, mock_repo_provider):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    larq = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larq)
    dbsession.flush()
    mock_repo_provider.get_compare.return_value = {"diff": "json"}
    task = LabelAnalysisRequestProcessingTask()
    task.errors = []
    parsed_diff = task._get_parsed_git_diff(larq)
    assert parsed_diff == ["parsed_git_diff"]
    mock_parse_diff.assert_called_with({"diff": "json"})
    mock_repo_provider.get_compare.assert_called_with(
        larq.base_commit.commitid, larq.head_commit.commitid
    )


@patch("tasks.label_analysis.parse_git_diff_json", return_value=["parsed_git_diff"])
def test__get_parsed_git_diff_error(mock_parse_diff, dbsession, mock_repo_provider):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    larq = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larq)
    dbsession.flush()
    mock_repo_provider.get_compare.side_effect = Exception("Oh no")
    task = LabelAnalysisRequestProcessingTask()
    task.errors = []
    task.dbsession = dbsession
    parsed_diff = task._get_parsed_git_diff(larq)
    assert parsed_diff is None
    mock_parse_diff.assert_not_called()
    mock_repo_provider.get_compare.assert_called_with(
        larq.base_commit.commitid, larq.head_commit.commitid
    )


@patch(
    "tasks.label_analysis.LabelAnalysisRequestProcessingTask.get_relevant_executable_lines",
    return_value=[{"all": False, "files": {}}],
)
@patch(
    "tasks.label_analysis.LabelAnalysisRequestProcessingTask._get_parsed_git_diff",
    return_value=["parsed_git_diff"],
)
def test__get_lines_relevant_to_diff(
    mock_parse_diff, mock_get_relevant_lines, dbsession
):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    larq = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larq)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    lines = task._get_lines_relevant_to_diff(larq)
    assert lines == [{"all": False, "files": {}}]
    mock_parse_diff.assert_called_with(larq)
    mock_get_relevant_lines.assert_called_with(larq, ["parsed_git_diff"])


@patch(
    "tasks.label_analysis.LabelAnalysisRequestProcessingTask.get_relevant_executable_lines"
)
@patch(
    "tasks.label_analysis.LabelAnalysisRequestProcessingTask._get_parsed_git_diff",
    return_value=None,
)
def test__get_lines_relevant_to_diff_error(
    mock_parse_diff, mock_get_relevant_lines, dbsession
):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    larq = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larq)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    lines = task._get_lines_relevant_to_diff(larq)
    assert lines is None
    mock_parse_diff.assert_called_with(larq)
    mock_get_relevant_lines.assert_not_called()
