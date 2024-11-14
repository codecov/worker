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
from services.report.raw_upload_processor import (
    SessionAdjustmentResult,
    clear_carryforward_sessions,
)
from test_utils.base import BaseTestCase

# Not calling add_sessions here on purpose, so it doesnt
#   interfere with this logic


class TestAdjustSession(BaseTestCase):
    @pytest.fixture
    def sample_first_report(self):
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
            [[SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label]],
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
                label_ids=labels,
            )
            for labels in (list_of_lists_of_labels or [[]])
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

    def test_adjust_sessions_no_cf(self, sample_first_report):
        first_value = self.convert_report_to_better_readable(sample_first_report)
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(sessions={3: first_to_merge_session})
        current_yaml = UserYaml({})
        assert clear_carryforward_sessions(
            sample_first_report, second_report, ["enterprise"], current_yaml
        ) == SessionAdjustmentResult([], [])
        assert first_value == self.convert_report_to_better_readable(
            sample_first_report
        )

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
        assert clear_carryforward_sessions(
            sample_first_report, second_report, ["enterprise"], current_yaml
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
                            (2, 14, None, ["another_label", "one_label"]),
                            (3, 7, None, ["another_label"]),
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
                            (1, 1, None, ["one_label"]),
                            (3, 15, None, ["another_label", "one_label"]),
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
                        [[3, 11, None, None, None], [2, 18, None, None, None]],
                        None,
                        None,
                        [
                            (2, 18, None, ["Th2dMtk4M_codecov"]),
                            (3, 11, None, ["another_label"]),
                            (3, 11, None, ["one_label"]),
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
            },
            "report": {
                "files": {
                    "first_file.py": [
                        0,
                        [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        None,
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

    def test_adjust_sessions_partial_cf_only_no_changes(
        self, sample_first_report, mocker
    ):
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(
            sessions={first_to_merge_session.id: first_to_merge_session}
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
        assert clear_carryforward_sessions(
            sample_first_report, second_report, ["enterprise"], current_yaml
        ) == SessionAdjustmentResult([], [0])
        after_result = self.convert_report_to_better_readable(sample_first_report)
        assert after_result == first_value

    def test_adjust_sessions_partial_cf_only_no_changes_encoding_labels(
        self, sample_first_report, mocker
    ):
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(
            sessions={first_to_merge_session.id: first_to_merge_session}
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
        assert clear_carryforward_sessions(
            sample_first_report,
            second_report,
            ["enterprise"],
            current_yaml,
            upload=upload,
        ) == SessionAdjustmentResult([], [0])
        after_result = self.convert_report_to_better_readable(sample_first_report)
        assert after_result == first_value

    def test_adjust_sessions_partial_cf_only_some_changes(self, sample_first_report):
        first_to_merge_session = Session(flags=["enterprise"], id=3)
        second_report = Report(
            sessions={first_to_merge_session.id: first_to_merge_session}
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
                coverage=90, sessionid=3, list_of_lists_of_labels=[["one_label"]]
            ),
        )
        second_report.append(second_report_file)
        assert clear_carryforward_sessions(
            sample_first_report, second_report, ["enterprise"], current_yaml
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
                        [[1, 5, None, None, None], [3, 19, None, None, None]],
                        None,
                        None,
                        [
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
            },
            "report": {
                "files": {
                    "first_file.py": [
                        0,
                        [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        None,
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
        self, sample_first_report
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

        second_report_file = ReportFile("unrelatedfile.py")
        second_report_file.append(
            90,
            self.create_sample_line(
                coverage=90, sessionid=3, list_of_lists_of_labels=[["one_label"]]
            ),
        )
        a_report_file = ReportFile("first_file.py")
        a_report_file.append(
            90,
            self.create_sample_line(
                coverage=90,
                sessionid=3,
                list_of_lists_of_labels=[
                    ["another_label"],
                    [
                        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label
                    ],
                ],
            ),
        )
        second_report.append(second_report_file)
        second_report.append(a_report_file)
        assert clear_carryforward_sessions(
            sample_first_report, second_report, ["enterprise"], current_yaml
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
                        (2, 14, None, ["another_label", "one_label"]),
                        (3, 7, None, ["another_label"]),
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
                        (1, 1, None, ["one_label"]),
                        (3, 15, None, ["another_label", "one_label"]),
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
                    [[3, 11, None, None, None], [2, 18, None, None, None]],
                    None,
                    None,
                    [
                        (2, 18, None, ["Th2dMtk4M_codecov"]),
                        (3, 11, None, ["another_label"]),
                        (3, 11, None, ["one_label"]),
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
                (2, 14, None, ["another_label", "one_label"]),
                (3, 7, None, ["another_label"]),
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
                (1, 1, None, ["one_label"]),
                (3, 15, None, ["another_label", "one_label"]),
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
            [[3, 11, None, None, None], [2, 18, None, None, None]],
            None,
            None,
            [
                (2, 18, None, ["Th2dMtk4M_codecov"]),
                (3, 11, None, ["another_label"]),
                (3, 11, None, ["one_label"]),
            ],
        ),
        (
            6,
            19,
            None,
            [[1, 5, None, None, None], [3, 19, None, None, None]],
            None,
            None,
            [(1, 5, None, ["another_label"]), (3, 19, None, ["Th2dMtk4M_codecov"])],
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
