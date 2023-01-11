import json

import pytest

from database.tests.factories.core import RepositoryFactory
from database.tests.factories.staticanalysis import (
    StaticAnalysisSingleFileSnapshotFactory,
    StaticAnalysisSuiteFactory,
    StaticAnalysisSuiteFilepathFactory,
)
from services.static_analysis import (
    SingleFileSnapshotAnalyzer,
    StaticAnalysisComparisonService,
    _get_analysis_content_mapping,
)
from services.static_analysis.git_diff_parser import DiffChange, DiffChangeType


def test_get_analysis_content_mapping(dbsession):
    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()
    static_analysis_suite = StaticAnalysisSuiteFactory.create(
        commit__repository=repository
    )
    secondary_static_analysis = StaticAnalysisSuiteFactory.create(
        commit__repository=repository
    )
    dbsession.add(static_analysis_suite)
    dbsession.add(secondary_static_analysis)
    dbsession.flush()
    snapshot_1 = StaticAnalysisSingleFileSnapshotFactory.create(repository=repository)
    snapshot_2 = StaticAnalysisSingleFileSnapshotFactory.create(repository=repository)
    snapshot_3 = StaticAnalysisSingleFileSnapshotFactory.create(repository=repository)
    snapshot_4 = StaticAnalysisSingleFileSnapshotFactory.create(repository=repository)
    snapshot_5 = StaticAnalysisSingleFileSnapshotFactory.create(repository=repository)
    dbsession.add_all([snapshot_1, snapshot_2, snapshot_3, snapshot_4, snapshot_5])
    dbsession.flush()
    f_1 = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=snapshot_1, analysis_suite=static_analysis_suite
    )
    f_2 = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=snapshot_2, analysis_suite=static_analysis_suite
    )
    f_3 = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=snapshot_3, analysis_suite=static_analysis_suite
    )
    f_4 = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=snapshot_4, analysis_suite=static_analysis_suite
    )
    f_s_2 = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=snapshot_2,
        analysis_suite=secondary_static_analysis,
        filepath=f_1.filepath,
    )
    f_s_3 = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=snapshot_3, analysis_suite=secondary_static_analysis
    )
    f_s_5 = StaticAnalysisSuiteFilepathFactory.create(
        file_snapshot=snapshot_5, analysis_suite=secondary_static_analysis
    )
    dbsession.add_all([f_1, f_2, f_3, f_4, f_s_2, f_s_3, f_s_5])
    dbsession.flush()
    first_res = _get_analysis_content_mapping(
        static_analysis_suite,
        [f_1.filepath, f_2.filepath, f_4.filepath, "somenonexistent.gh"],
    )
    assert first_res == {
        f_1.filepath: snapshot_1.content_location,
        f_2.filepath: snapshot_2.content_location,
        f_4.filepath: snapshot_4.content_location,
    }
    secondary_res = _get_analysis_content_mapping(
        secondary_static_analysis,
        [f_s_2.filepath, f_s_3.filepath],
    )
    assert secondary_res == {
        f_s_2.filepath: snapshot_2.content_location,
        f_s_3.filepath: snapshot_3.content_location,
    }


@pytest.fixture()
def sample_service(dbsession):
    repository = RepositoryFactory.create()
    head_static_analysis = StaticAnalysisSuiteFactory.create(
        commit__repository=repository
    )
    base_static_analysis = StaticAnalysisSuiteFactory.create(
        commit__repository=repository
    )
    dbsession.add(head_static_analysis)
    dbsession.add(base_static_analysis)
    dbsession.flush()
    return StaticAnalysisComparisonService(
        base_static_analysis=base_static_analysis,
        head_static_analysis=head_static_analysis,
        git_diff=[
            DiffChange(
                before_filepath="path/changed.py",
                after_filepath="path/changed.py",
                change_type=DiffChangeType.modified,
                lines_only_on_base=[],
                lines_only_on_head=[20],
            ),
        ],
    )


class TestStaticAnalysisComparisonService(object):
    def test_load_snapshot_data_unhappy_cases(self, sample_service, mock_storage):
        assert sample_service._load_snapshot_data("filepath", None) is None
        assert sample_service._load_snapshot_data("filepath", "fake_location") is None

    def test_load_snapshot_data_happy_cases(self, sample_service, mock_storage):
        mock_storage.write_file(
            "archive",
            "real_content_location",
            json.dumps({"statements": [(1, {"ha": "pokemon"})]}),
        )
        res = sample_service._load_snapshot_data("filepath", "real_content_location")
        assert isinstance(res, SingleFileSnapshotAnalyzer)
        assert res._filepath == "filepath"
        assert res._analysis_file_data == {"statements": [[1, {"ha": "pokemon"}]]}
        assert res._statement_mapping == {1: {"ha": "pokemon"}}

    def test_get_base_lines_relevant_to_change_deleted_plus_changed_normal(
        self, dbsession, mock_storage
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        snapshot_deleted = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_base = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_head = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        dbsession.add_all(
            [
                snapshot_deleted,
                changed_snapshot_base,
                changed_snapshot_head,
            ]
        )
        dbsession.flush()
        mock_storage.write_file(
            "archive", snapshot_deleted.content_location, json.dumps({"statements": []})
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_base.content_location,
            json.dumps(
                {
                    "statements": [
                        (
                            30,
                            {
                                "len": 1,
                                "line_surety_ancestorship": 29,
                                "extra_connected_lines": [35],
                            },
                        ),
                    ]
                }
            ),
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_head.content_location,
            json.dumps(
                {
                    "functions": [],
                    "statements": [
                        (1, {"len": 0, "extra_connected_lines": []}),
                        (2, {"len": 1, "extra_connected_lines": []}),
                        (8, {"len": 0, "extra_connected_lines": []}),
                        (
                            10,
                            {
                                "len": 1,
                                "line_surety_ancestorship": 8,
                                "extra_connected_lines": [20],
                            },
                        ),
                    ],
                }
            ),
        )
        head_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        base_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        dbsession.add(head_static_analysis)
        dbsession.add(base_static_analysis)
        dbsession.flush()
        deleted_sasff = StaticAnalysisSuiteFilepathFactory.create(
            file_snapshot=snapshot_deleted,
            analysis_suite=base_static_analysis,
            filepath="deleted.py",
        )
        old_changed_sasff = StaticAnalysisSuiteFilepathFactory.create(
            file_snapshot=changed_snapshot_base,
            analysis_suite=base_static_analysis,
            filepath="path/changed.py",
        )
        new_changed_sasff = StaticAnalysisSuiteFilepathFactory.create(
            file_snapshot=changed_snapshot_head,
            analysis_suite=head_static_analysis,
            filepath="path/changed.py",
        )
        dbsession.add_all([deleted_sasff, old_changed_sasff, new_changed_sasff])
        dbsession.flush()
        service = StaticAnalysisComparisonService(
            base_static_analysis=base_static_analysis,
            head_static_analysis=head_static_analysis,
            git_diff=[
                DiffChange(
                    before_filepath="path/changed.py",
                    after_filepath="path/changed.py",
                    change_type=DiffChangeType.modified,
                    lines_only_on_base=[30],
                    lines_only_on_head=[20],
                ),
                DiffChange(
                    before_filepath="deleted.py",
                    after_filepath=None,
                    change_type=DiffChangeType.deleted,
                    lines_only_on_base=None,
                    lines_only_on_head=None,
                ),
            ],
        )
        assert service.get_base_lines_relevant_to_change() == {
            "all": False,
            "files": {
                "deleted.py": {"all": True, "lines": None},
                "path/changed.py": {"all": False, "lines": {8, 30}},
            },
        }

    def test_get_base_lines_relevant_to_change_one_new_file(
        self, dbsession, mock_storage
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        snapshot_deleted = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_base = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_head = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        dbsession.add_all(
            [
                snapshot_deleted,
                changed_snapshot_base,
                changed_snapshot_head,
            ]
        )
        dbsession.flush()
        mock_storage.write_file(
            "archive", snapshot_deleted.content_location, json.dumps({"statements": []})
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_base.content_location,
            json.dumps({"statements": [(1, {})]}),
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_head.content_location,
            json.dumps(
                {
                    "functions": [],
                    "statements": [
                        (1, {"len": 0, "extra_connected_lines": []}),
                        (2, {"len": 1, "extra_connected_lines": []}),
                        (8, {"len": 0, "extra_connected_lines": []}),
                        (
                            10,
                            {
                                "len": 1,
                                "line_surety_ancestorship": 8,
                                "extra_connected_lines": [20],
                            },
                        ),
                    ],
                }
            ),
        )
        head_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        base_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        dbsession.add(head_static_analysis)
        dbsession.add(base_static_analysis)
        dbsession.flush()
        deleted_sasff = StaticAnalysisSuiteFilepathFactory.create(
            file_snapshot=snapshot_deleted,
            analysis_suite=base_static_analysis,
            filepath="deleted.py",
        )
        old_changed_sasff = StaticAnalysisSuiteFilepathFactory.create(
            file_snapshot=changed_snapshot_base,
            analysis_suite=base_static_analysis,
            filepath="path/changed.py",
        )
        new_changed_sasff = StaticAnalysisSuiteFilepathFactory.create(
            file_snapshot=changed_snapshot_head,
            analysis_suite=head_static_analysis,
            filepath="path/changed.py",
        )
        dbsession.add_all([deleted_sasff, old_changed_sasff, new_changed_sasff])
        dbsession.flush()
        service = StaticAnalysisComparisonService(
            base_static_analysis=base_static_analysis,
            head_static_analysis=head_static_analysis,
            git_diff=[
                DiffChange(
                    before_filepath="path/changed.py",
                    after_filepath="path/changed.py",
                    change_type=DiffChangeType.modified,
                    lines_only_on_base=[],
                    lines_only_on_head=[20],
                ),
                DiffChange(
                    before_filepath=None,
                    after_filepath="path/new.py",
                    change_type=DiffChangeType.new,
                    lines_only_on_base=[],
                    lines_only_on_head=[20],
                ),
                DiffChange(
                    before_filepath="deleted.py",
                    after_filepath=None,
                    change_type=DiffChangeType.deleted,
                    lines_only_on_base=None,
                    lines_only_on_head=None,
                ),
            ],
        )
        assert service.get_base_lines_relevant_to_change() == {"all": True}

    def test_analyze_single_change_first_line_file(self, dbsession, mock_storage):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        changed_snapshot_base = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_head = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        dbsession.add_all(
            [
                changed_snapshot_base,
                changed_snapshot_head,
            ]
        )
        dbsession.flush()
        mock_storage.write_file(
            "archive",
            changed_snapshot_base.content_location,
            json.dumps(
                {
                    "statements": [
                        (
                            6,
                            {
                                "len": 1,
                                "extra_connected_lines": [9],
                            },
                        ),
                    ]
                }
            ),
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_head.content_location,
            json.dumps(
                {
                    "functions": [],
                    "statements": [
                        (
                            10,
                            {
                                "len": 0,
                                "extra_connected_lines": [20],
                            },
                        ),
                        (
                            11,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 10,
                                "extra_connected_lines": [],
                            },
                        ),
                        (12, {"len": 1, "extra_connected_lines": []}),
                        (
                            18,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 12,
                                "extra_connected_lines": [],
                            },
                        ),
                    ],
                }
            ),
        )
        head_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        base_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        dbsession.add(head_static_analysis)
        dbsession.add(base_static_analysis)
        dbsession.flush()
        change = DiffChange(
            before_filepath="path/changed.py",
            after_filepath="path/changed.py",
            change_type=DiffChangeType.modified,
            lines_only_on_base=[9],
            lines_only_on_head=[11],
        )
        service = StaticAnalysisComparisonService(
            base_static_analysis=base_static_analysis,
            head_static_analysis=head_static_analysis,
            git_diff=[change],
        )
        assert service._analyze_single_change(
            dbsession,
            change,
            changed_snapshot_base.content_location,
            changed_snapshot_head.content_location,
        ) == {"all": False, "lines": {6, 10}}

    def test_analyze_single_change_base_change(self, dbsession, mock_storage):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        changed_snapshot_base = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_head = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        dbsession.add_all(
            [
                changed_snapshot_base,
                changed_snapshot_head,
            ]
        )
        dbsession.flush()
        mock_storage.write_file(
            "archive",
            changed_snapshot_base.content_location,
            json.dumps(
                {
                    "functions": [
                        {
                            "identifier": "banana_function",
                            "start_line": 3,
                            "end_line": 8,
                        }
                    ],
                    "statements": [
                        (
                            1,
                            {
                                "len": 0,
                                "line_surety_ancestorship": None,
                                "extra_connected_lines": [],
                            },
                        ),
                        (
                            2,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 1,
                                "extra_connected_lines": [],
                            },
                        ),
                    ],
                }
            ),
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_head.content_location,
            json.dumps(
                {
                    "functions": [
                        {
                            "identifier": "banana_function",
                            "start_line": 3,
                            "end_line": 8,
                        }
                    ],
                    "statements": [
                        (
                            10,
                            {
                                "len": 1,
                                "extra_connected_lines": [20],
                            },
                        ),
                        (
                            11,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 10,
                                "extra_connected_lines": [],
                            },
                        ),
                        (12, {"len": 1, "extra_connected_lines": []}),
                        (
                            18,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 12,
                                "extra_connected_lines": [],
                            },
                        ),
                    ],
                }
            ),
        )
        head_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        base_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        dbsession.add(head_static_analysis)
        dbsession.add(base_static_analysis)
        dbsession.flush()
        service = StaticAnalysisComparisonService(
            base_static_analysis=base_static_analysis,
            head_static_analysis=head_static_analysis,
            git_diff=[
                DiffChange(
                    before_filepath="path/changed.py",
                    after_filepath="path/changed.py",
                    change_type=DiffChangeType.modified,
                    lines_only_on_base=[],
                    lines_only_on_head=[20],
                ),
            ],
        )
        assert service._analyze_single_change(
            dbsession,
            DiffChange(
                before_filepath="path/changed.py",
                after_filepath="path/changed.py",
                change_type=DiffChangeType.modified,
                lines_only_on_base=[],
                lines_only_on_head=[20],
            ),
            changed_snapshot_base.content_location,
            changed_snapshot_head.content_location,
        ) == {"all": True, "lines": None}
        assert service._analyze_single_change(
            dbsession,
            DiffChange(
                before_filepath="path/changed.py",
                after_filepath="path/changed.py",
                change_type=DiffChangeType.modified,
                lines_only_on_base=[],
                lines_only_on_head=[99, 100],
            ),
            changed_snapshot_base.content_location,
            changed_snapshot_head.content_location,
        ) == {"all": False, "lines": set()}

    def test_analyze_single_change_function_based(self, dbsession, mock_storage):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        changed_snapshot_base = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_head = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        dbsession.add_all(
            [
                changed_snapshot_base,
                changed_snapshot_head,
            ]
        )
        dbsession.flush()
        mock_storage.write_file(
            "archive",
            changed_snapshot_base.content_location,
            json.dumps(
                {
                    "functions": [
                        {
                            "identifier": "banana_function",
                            "start_line": 3,
                            "end_line": 8,
                        }
                    ],
                    "statements": [(1, {})],
                }
            ),
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_head.content_location,
            json.dumps(
                {
                    "functions": [
                        {
                            "identifier": "banana_function",
                            "start_line": 9,
                            "end_line": 11,
                        }
                    ],
                    "statements": [
                        (
                            10,
                            {
                                "len": 1,
                                "extra_connected_lines": [20],
                            },
                        ),
                        (
                            11,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 10,
                                "extra_connected_lines": [],
                            },
                        ),
                        (12, {"len": 1, "extra_connected_lines": []}),
                        (
                            18,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 12,
                                "extra_connected_lines": [],
                            },
                        ),
                    ],
                }
            ),
        )
        head_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        base_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        dbsession.add(head_static_analysis)
        dbsession.add(base_static_analysis)
        dbsession.flush()
        service = StaticAnalysisComparisonService(
            base_static_analysis=base_static_analysis,
            head_static_analysis=head_static_analysis,
            git_diff=[
                DiffChange(
                    before_filepath="path/changed.py",
                    after_filepath="path/changed.py",
                    change_type=DiffChangeType.modified,
                    lines_only_on_base=[],
                    lines_only_on_head=[20],
                ),
            ],
        )
        change = DiffChange(
            before_filepath="path/changed.py",
            after_filepath="path/changed.py",
            change_type=DiffChangeType.modified,
            lines_only_on_base=[],
            lines_only_on_head=[20],
        )
        assert service._analyze_single_change(
            dbsession,
            change,
            changed_snapshot_base.content_location,
            changed_snapshot_head.content_location,
        ) == {"all": False, "lines": {3}}

    def test_analyze_single_change_no_static_analysis_found(
        self, dbsession, mock_storage, mocker, sample_service
    ):
        mocked_load_snapshot = mocker.patch.object(
            StaticAnalysisComparisonService, "_load_snapshot_data", return_value=None
        )
        change = DiffChange(
            before_filepath="path/changed.py",
            after_filepath="path/changed.py",
            change_type=DiffChangeType.modified,
            lines_only_on_base=[],
            lines_only_on_head=[20],
        )
        first_location, second_location = mocker.MagicMock(), mocker.MagicMock()
        assert (
            sample_service._analyze_single_change(
                dbsession,
                change,
                first_location,
                second_location,
            )
            is None
        )
        assert mocked_load_snapshot.call_count == 2
        mocked_load_snapshot.assert_any_call("path/changed.py", second_location)
        mocked_load_snapshot.assert_any_call("path/changed.py", first_location)

    def test_analyze_single_change_function_based_no_function_found(
        self, dbsession, mock_storage
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        changed_snapshot_base = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        changed_snapshot_head = StaticAnalysisSingleFileSnapshotFactory.create(
            repository=repository
        )
        dbsession.add_all(
            [
                changed_snapshot_base,
                changed_snapshot_head,
            ]
        )
        dbsession.flush()
        mock_storage.write_file(
            "archive",
            changed_snapshot_base.content_location,
            json.dumps(
                {
                    "functions": [],
                    "statements": [(1, {})],
                }
            ),
        )
        mock_storage.write_file(
            "archive",
            changed_snapshot_head.content_location,
            json.dumps(
                {
                    "functions": [
                        {
                            "identifier": "banana_function",
                            "start_line": 9,
                            "end_line": 11,
                        }
                    ],
                    "statements": [
                        (
                            10,
                            {
                                "len": 1,
                                "extra_connected_lines": [20],
                            },
                        ),
                        (
                            11,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 10,
                                "extra_connected_lines": [],
                            },
                        ),
                        (12, {"len": 1, "extra_connected_lines": []}),
                        (
                            18,
                            {
                                "len": 0,
                                "line_surety_ancestorship": 12,
                                "extra_connected_lines": [],
                            },
                        ),
                    ],
                }
            ),
        )
        head_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        base_static_analysis = StaticAnalysisSuiteFactory.create(
            commit__repository=repository
        )
        dbsession.add(head_static_analysis)
        dbsession.add(base_static_analysis)
        dbsession.flush()
        service = StaticAnalysisComparisonService(
            base_static_analysis=base_static_analysis,
            head_static_analysis=head_static_analysis,
            git_diff=[
                DiffChange(
                    before_filepath="path/changed.py",
                    after_filepath="path/changed.py",
                    change_type=DiffChangeType.modified,
                    lines_only_on_base=[],
                    lines_only_on_head=[20],
                ),
            ],
        )
        change = DiffChange(
            before_filepath="path/changed.py",
            after_filepath="path/changed.py",
            change_type=DiffChangeType.modified,
            lines_only_on_base=[],
            lines_only_on_head=[20],
        )
        assert service._analyze_single_change(
            dbsession,
            change,
            changed_snapshot_base.content_location,
            changed_snapshot_head.content_location,
        ) == {"all": True, "lines": None}
