import pytest
from mock import MagicMock
from shared.reports.editable import EditableReport, EditableReportFile
from shared.reports.resources import (
    LineSession,
    Report,
    ReportFile,
    ReportLine,
    Session,
    SessionType,
)
from shared.reports.types import CoverageDatapoint
from shared.yaml import UserYaml

from helpers.labels import SpecialLabelsEnum
from rollouts import USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID
from services.report.raw_upload_processor import (
    SessionAdjustmentResult,
    _adjust_sessions,
    make_sure_label_indexes_match,
)
from test_utils.base import BaseTestCase

# Not calling add_sessions here on purpose, so it doesnt
#   interfere with this logic


class TestAdjustSession(BaseTestCase):
    @pytest.fixture
    def sample_first_report(self):
        report_label_idx = {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "one_label",
            2: "another_label",
        }
        first_report = EditableReport(
            sessions={
                0: Session(
                    flags=["enterprise"],
                    id=0,
                    session_type=SessionType.carriedforward,
                ),
                1: Session(
                    flags=["enterprise"], id=1, session_type=SessionType.uploaded
                ),
                2: Session(
                    flags=["unit"], id=2, session_type=SessionType.carriedforward
                ),
                3: Session(
                    flags=["unrelated"], id=3, session_type=SessionType.uploaded
                ),
            }
        )
        first_file = EditableReportFile("first_file.py")
        c = 0
        for list_of_lists_of_labels in [
            [[1]],
            [[2]],
            [[2], [1]],
            [[2, 1]],
            [[0]],
        ]:
            for sessionid in range(4):
                first_file.append(
                    c % 7 + 1,
                    self.create_sample_line(
                        coverage=c,
                        sessionid=sessionid,
                        list_of_lists_of_labels=list_of_lists_of_labels,
                    ),
                )
                c += 1
        second_file = EditableReportFile("second_file.py")
        first_report.append(first_file)
        first_report.append(second_file)
        # print(self.convert_report_to_better_readable(first_report)["archive"])
        assert self.convert_report_to_better_readable(first_report)["archive"] == {
            "first_file.py": [
                (
                    1,
                    14,
                    None,
                    [
                        [0, 0, None, None, None],
                        [3, 7, None, None, None],
                        [2, 14, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 0, None, [1]),
                        (2, 14, None, [2, 1]),
                        (3, 7, None, [2]),
                    ],
                ),
                (
                    2,
                    15,
                    None,
                    [
                        [1, 1, None, None, None],
                        [0, 8, None, None, None],
                        [3, 15, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 8, None, [1]),
                        (0, 8, None, [2]),
                        (1, 1, None, [1]),
                        (3, 15, None, [2, 1]),
                    ],
                ),
                (
                    3,
                    16,
                    None,
                    [
                        [2, 2, None, None, None],
                        [1, 9, None, None, None],
                        [0, 16, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 16, None, [0]),
                        (1, 9, None, [1]),
                        (1, 9, None, [2]),
                        (2, 2, None, [1]),
                    ],
                ),
                (
                    4,
                    17,
                    None,
                    [
                        [3, 3, None, None, None],
                        [2, 10, None, None, None],
                        [1, 17, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (1, 17, None, [0]),
                        (2, 10, None, [1]),
                        (2, 10, None, [2]),
                        (3, 3, None, [1]),
                    ],
                ),
                (
                    5,
                    18,
                    None,
                    [
                        [0, 4, None, None, None],
                        [3, 11, None, None, None],
                        [2, 18, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 4, None, [2]),
                        (2, 18, None, [0]),
                        (3, 11, None, [1]),
                        (3, 11, None, [2]),
                    ],
                ),
                (
                    6,
                    19,
                    None,
                    [
                        [1, 5, None, None, None],
                        [0, 12, None, None, None],
                        [3, 19, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 12, None, [2, 1]),
                        (1, 5, None, [2]),
                        (3, 19, None, [0]),
                    ],
                ),
                (
                    7,
                    13,
                    None,
                    [[2, 6, None, None, None], [1, 13, None, None, None]],
                    None,
                    None,
                    [
                        (1, 13, None, [2, 1]),
                        (2, 6, None, [2]),
                    ],
                ),
            ]
        }
        first_report.labels_index = report_label_idx
        return first_report

    @pytest.fixture
    def sample_first_report_no_encoded_labels(self):
        first_report = EditableReport(
            sessions={
                0: Session(
                    flags=["enterprise"],
                    id=0,
                    session_type=SessionType.carriedforward,
                ),
                1: Session(
                    flags=["enterprise"], id=1, session_type=SessionType.uploaded
                ),
                2: Session(
                    flags=["unit"], id=2, session_type=SessionType.carriedforward
                ),
                3: Session(
                    flags=["unrelated"], id=3, session_type=SessionType.uploaded
                ),
            }
        )
        first_file = EditableReportFile("first_file.py")
        c = 0
        for list_of_lists_of_labels in [
            [["one_label"]],
            [["another_label"]],
            [["another_label"], ["one_label"]],
            [["another_label", "one_label"]],
            [["Th2dMtk4M_codecov"]],
        ]:
            for sessionid in range(4):
                first_file.append(
                    c % 7 + 1,
                    self.create_sample_line(
                        coverage=c,
                        sessionid=sessionid,
                        list_of_lists_of_labels=list_of_lists_of_labels,
                    ),
                )
                c += 1
        second_file = EditableReportFile("second_file.py")
        first_report.append(first_file)
        first_report.append(second_file)
        # print(self.convert_report_to_better_readable(first_report)["archive"])
        assert self.convert_report_to_better_readable(first_report)["archive"] == {
            "first_file.py": [
                (
                    1,
                    14,
                    None,
                    [
                        [0, 0, None, None, None],
                        [3, 7, None, None, None],
                        [2, 14, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 0, None, ["one_label"]),
                        (2, 14, None, ["another_label", "one_label"]),
                        (3, 7, None, ["another_label"]),
                    ],
                ),
                (
                    2,
                    15,
                    None,
                    [
                        [1, 1, None, None, None],
                        [0, 8, None, None, None],
                        [3, 15, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 8, None, ["another_label"]),
                        (0, 8, None, ["one_label"]),
                        (1, 1, None, ["one_label"]),
                        (3, 15, None, ["another_label", "one_label"]),
                    ],
                ),
                (
                    3,
                    16,
                    None,
                    [
                        [2, 2, None, None, None],
                        [1, 9, None, None, None],
                        [0, 16, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 16, None, ["Th2dMtk4M_codecov"]),
                        (1, 9, None, ["another_label"]),
                        (1, 9, None, ["one_label"]),
                        (2, 2, None, ["one_label"]),
                    ],
                ),
                (
                    4,
                    17,
                    None,
                    [
                        [3, 3, None, None, None],
                        [2, 10, None, None, None],
                        [1, 17, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (1, 17, None, ["Th2dMtk4M_codecov"]),
                        (2, 10, None, ["another_label"]),
                        (2, 10, None, ["one_label"]),
                        (3, 3, None, ["one_label"]),
                    ],
                ),
                (
                    5,
                    18,
                    None,
                    [
                        [0, 4, None, None, None],
                        [3, 11, None, None, None],
                        [2, 18, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 4, None, ["another_label"]),
                        (2, 18, None, ["Th2dMtk4M_codecov"]),
                        (3, 11, None, ["another_label"]),
                        (3, 11, None, ["one_label"]),
                    ],
                ),
                (
                    6,
                    19,
                    None,
                    [
                        [1, 5, None, None, None],
                        [0, 12, None, None, None],
                        [3, 19, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (0, 12, None, ["another_label", "one_label"]),
                        (1, 5, None, ["another_label"]),
                        (3, 19, None, ["Th2dMtk4M_codecov"]),
                    ],
                ),
                (
                    7,
                    13,
                    None,
                    [[2, 6, None, None, None], [1, 13, None, None, None]],
                    None,
                    None,
                    [
                        (1, 13, None, ["another_label", "one_label"]),
                        (2, 6, None, ["another_label"]),
                    ],
                ),
            ]
        }
        return first_report

    def create_sample_line(
        self, *, coverage, sessionid=None, list_of_lists_of_labels=None
    ):
        datapoints = [
            CoverageDatapoint(
                sessionid=sessionid,
                coverage=coverage,
                coverage_type=None,
                label_ids=label_ids,
            )
            for label_ids in (list_of_lists_of_labels or [[]])
        ]
        return ReportLine.create(
            coverage=coverage,
            sessions=[
                (
                    LineSession(
                        id=sessionid,
                        coverage=coverage,
                    )
                )
            ],
            datapoints=datapoints,
        )

    @pytest.mark.parametrize("report_idx", [0, 1])
    def test_adjust_sessions_no_cf(
        self, sample_first_report, sample_first_report_no_encoded_labels, report_idx
    ):
        report_under_test = [
            sample_first_report,
            sample_first_report_no_encoded_labels,
        ][report_idx]
        first_value = self.convert_report_to_better_readable(report_under_test)
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(sessions={3: first_to_merge_session})
        current_yaml = UserYaml({})
        # No change to the report cause there's no session to CF
        assert _adjust_sessions(
            report_under_test, second_report, first_to_merge_session, current_yaml
        ) == SessionAdjustmentResult([], [])
        assert first_value == self.convert_report_to_better_readable(report_under_test)

    def test_adjust_sessions_full_cf_only(self, sample_first_report):
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(sessions={3: first_to_merge_session})
        current_yaml = UserYaml(
            {
                "flag_management": {
                    "individual_flags": [{"name": "enterprise", "carryforward": True}]
                }
            }
        )
        assert _adjust_sessions(
            sample_first_report, second_report, first_to_merge_session, current_yaml
        ) == SessionAdjustmentResult([0], [])
        print(self.convert_report_to_better_readable(sample_first_report))
        assert self.convert_report_to_better_readable(sample_first_report) == {
            "archive": {
                "first_file.py": [
                    (
                        1,
                        14,
                        None,
                        [[3, 7, None, None, None], [2, 14, None, None, None]],
                        None,
                        None,
                        [
                            (2, 14, None, [2, 1]),
                            (3, 7, None, [2]),
                        ],
                    ),
                    (
                        2,
                        15,
                        None,
                        [[1, 1, None, None, None], [3, 15, None, None, None]],
                        None,
                        None,
                        [
                            (1, 1, None, [1]),
                            (3, 15, None, [2, 1]),
                        ],
                    ),
                    (
                        3,
                        9,
                        None,
                        [[2, 2, None, None, None], [1, 9, None, None, None]],
                        None,
                        None,
                        [
                            (1, 9, None, [1]),
                            (1, 9, None, [2]),
                            (2, 2, None, [1]),
                        ],
                    ),
                    (
                        4,
                        17,
                        None,
                        [
                            [3, 3, None, None, None],
                            [2, 10, None, None, None],
                            [1, 17, None, None, None],
                        ],
                        None,
                        None,
                        [
                            (1, 17, None, [0]),
                            (2, 10, None, [1]),
                            (2, 10, None, [2]),
                            (3, 3, None, [1]),
                        ],
                    ),
                    (
                        5,
                        18,
                        None,
                        [[3, 11, None, None, None], [2, 18, None, None, None]],
                        None,
                        None,
                        [
                            (2, 18, None, [0]),
                            (3, 11, None, [1]),
                            (3, 11, None, [2]),
                        ],
                    ),
                    (
                        6,
                        19,
                        None,
                        [[1, 5, None, None, None], [3, 19, None, None, None]],
                        None,
                        None,
                        [
                            (1, 5, None, [2]),
                            (3, 19, None, [0]),
                        ],
                    ),
                    (
                        7,
                        13,
                        None,
                        [[2, 6, None, None, None], [1, 13, None, None, None]],
                        None,
                        None,
                        [
                            (1, 13, None, [2, 1]),
                            (2, 6, None, [2]),
                        ],
                    ),
                ]
            },
            "report": {
                "files": {
                    "first_file.py": [
                        0,
                        [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        None,
                    ]
                },
                "sessions": {
                    "1": {
                        "t": None,
                        "d": None,
                        "a": None,
                        "f": ["enterprise"],
                        "c": None,
                        "n": None,
                        "N": None,
                        "j": None,
                        "u": None,
                        "p": None,
                        "e": None,
                        "st": "uploaded",
                        "se": {},
                    },
                    "2": {
                        "t": None,
                        "d": None,
                        "a": None,
                        "f": ["unit"],
                        "c": None,
                        "n": None,
                        "N": None,
                        "j": None,
                        "u": None,
                        "p": None,
                        "e": None,
                        "st": "carriedforward",
                        "se": {},
                    },
                    "3": {
                        "t": None,
                        "d": None,
                        "a": None,
                        "f": ["unrelated"],
                        "c": None,
                        "n": None,
                        "N": None,
                        "j": None,
                        "u": None,
                        "p": None,
                        "e": None,
                        "st": "uploaded",
                        "se": {},
                    },
                },
            },
            "totals": {
                "f": 1,
                "n": 7,
                "h": 7,
                "m": 0,
                "p": 0,
                "c": "100",
                "b": 0,
                "d": 0,
                "M": 0,
                "s": 3,
                "C": 0,
                "N": 0,
                "diff": None,
            },
        }

    @pytest.mark.parametrize("report_idx", [0, 1])
    def test_adjust_sessions_partial_cf_only_no_changes(
        self,
        sample_first_report,
        sample_first_report_no_encoded_labels,
        mocker,
        report_idx,
    ):
        report_under_test = [
            sample_first_report,
            sample_first_report_no_encoded_labels,
        ][report_idx]

        mocker.patch.object(
            USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID,
            "check_value",
            return_value=True,
        )
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(
            sessions={first_to_merge_session.id: first_to_merge_session}
        )
        upload = MagicMock(
            name="fake_upload",
            **{
                "report": MagicMock(
                    name="fake_commit_report",
                    **{
                        "code": None,
                        "commit": MagicMock(
                            name="fake_commit",
                            **{"repository": MagicMock(name="fake_repo")},
                        ),
                    },
                )
            },
        )
        current_yaml = UserYaml(
            {
                "flag_management": {
                    "individual_flags": [
                        {
                            "name": "enterprise",
                            "carryforward_mode": "labels",
                            "carryforward": True,
                        }
                    ]
                }
            }
        )

        first_value = self.convert_report_to_better_readable(sample_first_report)
        # This makes changes to the not-label-encoded original report, encoding them
        assert _adjust_sessions(
            report_under_test,
            second_report,
            first_to_merge_session,
            current_yaml,
            upload=upload,
        ) == SessionAdjustmentResult([], [0])
        # The after result should always be the encoded labels one
        after_result = self.convert_report_to_better_readable(report_under_test)
        assert after_result == first_value

    def test_make_sure_label_indexes_match(self, sample_first_report):
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(
            sessions={first_to_merge_session.id: first_to_merge_session}
        )
        second_report.labels_index = {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            # Different from the original report
            2: "one_label",
            1: "another_label",
            # New labels
            3: "new_label",
        }
        second_report_file = ReportFile("unrelatedfile.py")
        second_report_file.append(
            90,
            self.create_sample_line(
                coverage=90, sessionid=3, list_of_lists_of_labels=[[2]]
            ),
        )
        second_report_file.append(
            89,
            self.create_sample_line(
                coverage=89, sessionid=3, list_of_lists_of_labels=[[1, 3]]
            ),
        )
        second_report.append(second_report_file)
        assert self.convert_report_to_better_readable(second_report)["archive"] == {
            "unrelatedfile.py": [
                (
                    89,
                    89,
                    None,
                    [[3, 89, None, None, None]],
                    None,
                    None,
                    [(3, 89, None, [1, 3])],
                ),
                (
                    90,
                    90,
                    None,
                    [[3, 90, None, None, None]],
                    None,
                    None,
                    [(3, 90, None, [2])],
                ),
            ]
        }
        assert sample_first_report.labels_index == {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "one_label",
            2: "another_label",
        }
        # This changes the label indexes in the 2nd report AND adds new labels to the original one.
        # So when we merge them we can be sure the indexes point to the same labels
        # And all labels are accounted for
        make_sure_label_indexes_match(sample_first_report, second_report)
        assert sample_first_report.labels_index == {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "one_label",
            2: "another_label",
            3: "new_label",
        }
        assert self.convert_report_to_better_readable(second_report)["archive"] == {
            "unrelatedfile.py": [
                (
                    89,
                    89,
                    None,
                    [[3, 89, None, None, None]],
                    None,
                    None,
                    [(3, 89, None, [2, 3])],
                ),
                (
                    90,
                    90,
                    None,
                    [[3, 90, None, None, None]],
                    None,
                    None,
                    [(3, 90, None, [1])],
                ),
            ]
        }

    def test_adjust_sessions_partial_cf_only_some_changes(
        self,
        sample_first_report,
        mocker,
    ):
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(
            sessions={first_to_merge_session.id: first_to_merge_session}
        )
        mocker.patch.object(
            USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID,
            "check_value",
            return_value=True,
        )
        upload = MagicMock(
            name="fake_upload",
            **{
                "report": MagicMock(
                    name="fake_commit_report",
                    **{
                        "code": None,
                        "commit": MagicMock(
                            name="fake_commit",
                            **{"repository": MagicMock(name="fake_repo")},
                        ),
                    },
                )
            },
        )
        current_yaml = UserYaml(
            {
                "flag_management": {
                    "individual_flags": [
                        {
                            "name": "enterprise",
                            "carryforward_mode": "labels",
                            "carryforward": True,
                        }
                    ]
                }
            }
        )
        second_report_file = ReportFile("unrelatedfile.py")
        second_report_file.append(
            90,
            self.create_sample_line(
                coverage=90, sessionid=3, list_of_lists_of_labels=[[1]]
            ),
        )
        second_report.append(second_report_file)
        assert _adjust_sessions(
            sample_first_report,
            second_report,
            first_to_merge_session,
            current_yaml,
            upload=upload,
        ) == SessionAdjustmentResult([], [0])
        print(self.convert_report_to_better_readable(sample_first_report))
        assert self.convert_report_to_better_readable(sample_first_report) == {
            "archive": {
                "first_file.py": [
                    (
                        1,
                        14,
                        None,
                        [[3, 7, None, None, None], [2, 14, None, None, None]],
                        None,
                        None,
                        [
                            (2, 14, None, [2, 1]),
                            (3, 7, None, [2]),
                        ],
                    ),
                    (
                        2,
                        15,
                        None,
                        [
                            [1, 1, None, None, None],
                            [0, 8, None, None, None],
                            [3, 15, None, None, None],
                        ],
                        None,
                        None,
                        [
                            (0, 8, None, [2]),
                            (1, 1, None, [1]),
                            (3, 15, None, [2, 1]),
                        ],
                    ),
                    (
                        3,
                        16,
                        None,
                        [
                            [2, 2, None, None, None],
                            [1, 9, None, None, None],
                            [0, 16, None, None, None],
                        ],
                        None,
                        None,
                        [
                            (0, 16, None, [0]),
                            (1, 9, None, [1]),
                            (1, 9, None, [2]),
                            (2, 2, None, [1]),
                        ],
                    ),
                    (
                        4,
                        17,
                        None,
                        [
                            [3, 3, None, None, None],
                            [2, 10, None, None, None],
                            [1, 17, None, None, None],
                        ],
                        None,
                        None,
                        [
                            (1, 17, None, [0]),
                            (2, 10, None, [1]),
                            (2, 10, None, [2]),
                            (3, 3, None, [1]),
                        ],
                    ),
                    (
                        5,
                        18,
                        None,
                        [
                            [0, 4, None, None, None],
                            [3, 11, None, None, None],
                            [2, 18, None, None, None],
                        ],
                        None,
                        None,
                        [
                            (0, 4, None, [2]),
                            (2, 18, None, [0]),
                            (3, 11, None, [1]),
                            (3, 11, None, [2]),
                        ],
                    ),
                    (
                        6,
                        19,
                        None,
                        [[1, 5, None, None, None], [3, 19, None, None, None]],
                        None,
                        None,
                        [
                            (1, 5, None, [2]),
                            (3, 19, None, [0]),
                        ],
                    ),
                    (
                        7,
                        13,
                        None,
                        [[2, 6, None, None, None], [1, 13, None, None, None]],
                        None,
                        None,
                        [
                            (1, 13, None, [2, 1]),
                            (2, 6, None, [2]),
                        ],
                    ),
                ]
            },
            "report": {
                "files": {
                    "first_file.py": [
                        0,
                        [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        None,
                    ]
                },
                "sessions": {
                    "0": {
                        "t": None,
                        "d": None,
                        "a": None,
                        "f": ["enterprise"],
                        "c": None,
                        "n": None,
                        "N": None,
                        "j": None,
                        "u": None,
                        "p": None,
                        "e": None,
                        "st": "carriedforward",
                        "se": {},
                    },
                    "1": {
                        "t": None,
                        "d": None,
                        "a": None,
                        "f": ["enterprise"],
                        "c": None,
                        "n": None,
                        "N": None,
                        "j": None,
                        "u": None,
                        "p": None,
                        "e": None,
                        "st": "uploaded",
                        "se": {},
                    },
                    "2": {
                        "t": None,
                        "d": None,
                        "a": None,
                        "f": ["unit"],
                        "c": None,
                        "n": None,
                        "N": None,
                        "j": None,
                        "u": None,
                        "p": None,
                        "e": None,
                        "st": "carriedforward",
                        "se": {},
                    },
                    "3": {
                        "t": None,
                        "d": None,
                        "a": None,
                        "f": ["unrelated"],
                        "c": None,
                        "n": None,
                        "N": None,
                        "j": None,
                        "u": None,
                        "p": None,
                        "e": None,
                        "st": "uploaded",
                        "se": {},
                    },
                },
            },
            "totals": {
                "f": 1,
                "n": 7,
                "h": 7,
                "m": 0,
                "p": 0,
                "c": "100",
                "b": 0,
                "d": 0,
                "M": 0,
                "s": 4,
                "C": 0,
                "N": 0,
                "diff": None,
            },
        }

    def test_adjust_sessions_partial_cf_only_full_deletion_due_to_lost_labels(
        self, sample_first_report, mocker
    ):
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(sessions={3: first_to_merge_session})
        current_yaml = UserYaml(
            {
                "flag_management": {
                    "individual_flags": [
                        {
                            "name": "enterprise",
                            "carryforward_mode": "labels",
                            "carryforward": True,
                        }
                    ]
                }
            }
        )
        upload = MagicMock(
            name="fake_upload",
            **{
                "report": MagicMock(
                    name="fake_commit_report",
                    **{
                        "code": None,
                        "commit": MagicMock(
                            name="fake_commit",
                            **{"repository": MagicMock(name="fake_repo")},
                        ),
                    },
                )
            },
        )
        mocker.patch.object(
            USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID,
            "check_value",
            return_value=True,
        )

        second_report_file = ReportFile("unrelatedfile.py")
        second_report_file.append(
            90,
            self.create_sample_line(
                coverage=90, sessionid=3, list_of_lists_of_labels=[[1]]
            ),
        )
        a_report_file = ReportFile("first_file.py")
        a_report_file.append(
            90,
            self.create_sample_line(
                coverage=90,
                sessionid=3,
                list_of_lists_of_labels=[
                    [2],
                    [0],
                ],
            ),
        )
        second_report.append(second_report_file)
        second_report.append(a_report_file)
        assert _adjust_sessions(
            sample_first_report,
            second_report,
            first_to_merge_session,
            current_yaml,
            upload=upload,
        ) == SessionAdjustmentResult([0], [])
        res = self.convert_report_to_better_readable(sample_first_report)
        # print(res["report"]["sessions"])
        assert res["report"]["sessions"] == {
            "1": {
                "t": None,
                "d": None,
                "a": None,
                "f": ["enterprise"],
                "c": None,
                "n": None,
                "N": None,
                "j": None,
                "u": None,
                "p": None,
                "e": None,
                "st": "uploaded",
                "se": {},
            },
            "2": {
                "t": None,
                "d": None,
                "a": None,
                "f": ["unit"],
                "c": None,
                "n": None,
                "N": None,
                "j": None,
                "u": None,
                "p": None,
                "e": None,
                "st": "carriedforward",
                "se": {},
            },
            "3": {
                "t": None,
                "d": None,
                "a": None,
                "f": ["unrelated"],
                "c": None,
                "n": None,
                "N": None,
                "j": None,
                "u": None,
                "p": None,
                "e": None,
                "st": "uploaded",
                "se": {},
            },
        }
        print(self.convert_report_to_better_readable(sample_first_report)["archive"])
        assert self.convert_report_to_better_readable(sample_first_report)[
            "archive"
        ] == {
            "first_file.py": [
                (
                    1,
                    14,
                    None,
                    [[3, 7, None, None, None], [2, 14, None, None, None]],
                    None,
                    None,
                    [
                        (2, 14, None, [2, 1]),
                        (3, 7, None, [2]),
                    ],
                ),
                (
                    2,
                    15,
                    None,
                    [[1, 1, None, None, None], [3, 15, None, None, None]],
                    None,
                    None,
                    [
                        (1, 1, None, [1]),
                        (3, 15, None, [2, 1]),
                    ],
                ),
                (
                    3,
                    9,
                    None,
                    [[2, 2, None, None, None], [1, 9, None, None, None]],
                    None,
                    None,
                    [
                        (1, 9, None, [1]),
                        (1, 9, None, [2]),
                        (2, 2, None, [1]),
                    ],
                ),
                (
                    4,
                    17,
                    None,
                    [
                        [3, 3, None, None, None],
                        [2, 10, None, None, None],
                        [1, 17, None, None, None],
                    ],
                    None,
                    None,
                    [
                        (1, 17, None, [0]),
                        (2, 10, None, [1]),
                        (2, 10, None, [2]),
                        (3, 3, None, [1]),
                    ],
                ),
                (
                    5,
                    18,
                    None,
                    [[3, 11, None, None, None], [2, 18, None, None, None]],
                    None,
                    None,
                    [
                        (2, 18, None, [0]),
                        (3, 11, None, [1]),
                        (3, 11, None, [2]),
                    ],
                ),
                (
                    6,
                    19,
                    None,
                    [[1, 5, None, None, None], [3, 19, None, None, None]],
                    None,
                    None,
                    [
                        (1, 5, None, [2]),
                        (3, 19, None, [0]),
                    ],
                ),
                (
                    7,
                    13,
                    None,
                    [[2, 6, None, None, None], [1, 13, None, None, None]],
                    None,
                    None,
                    [
                        (1, 13, None, [2, 1]),
                        (2, 6, None, [2]),
                    ],
                ),
            ]
        }


{
    "first_file.py": [
        (
            1,
            14,
            None,
            [[3, 7, None, None, None], [2, 14, None, None, None]],
            None,
            None,
            [
                (2, 14, None, [2, 1]),
                (3, 7, None, [2]),
            ],
        ),
        (
            2,
            15,
            None,
            [[1, 1, None, None, None], [3, 15, None, None, None]],
            None,
            None,
            [
                (1, 1, None, [1]),
                (3, 15, None, [2, 1]),
            ],
        ),
        (
            3,
            9,
            None,
            [[2, 2, None, None, None], [1, 9, None, None, None]],
            None,
            None,
            [
                (1, 9, None, [1]),
                (1, 9, None, [2]),
                (2, 2, None, [1]),
            ],
        ),
        (
            4,
            17,
            None,
            [
                [3, 3, None, None, None],
                [2, 10, None, None, None],
                [1, 17, None, None, None],
            ],
            None,
            None,
            [
                (1, 17, None, [0]),
                (2, 10, None, [1]),
                (2, 10, None, [2]),
                (3, 3, None, [1]),
            ],
        ),
        (
            5,
            18,
            None,
            [[3, 11, None, None, None], [2, 18, None, None, None]],
            None,
            None,
            [
                (2, 18, None, [0]),
                (3, 11, None, [1]),
                (3, 11, None, [2]),
            ],
        ),
        (
            6,
            19,
            None,
            [[1, 5, None, None, None], [3, 19, None, None, None]],
            None,
            None,
            [(1, 5, None, [2]), (3, 19, None, [0])],
        ),
        (
            7,
            13,
            None,
            [[2, 6, None, None, None], [1, 13, None, None, None]],
            None,
            None,
            [
                (1, 13, None, [2, 1]),
                (2, 6, None, [2]),
            ],
        ),
    ]
}
