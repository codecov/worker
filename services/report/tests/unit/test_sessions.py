import pytest
from shared.reports.editable import EditableReport, EditableReportFile
from shared.reports.resources import LineSession, ReportLine, Session, SessionType
from shared.yaml import UserYaml

from services.report.raw_upload_processor import clear_carryforward_sessions
from test_utils.base import BaseTestCase


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
        for _ in range(5):
            for sessionid in range(4):
                first_file.append(
                    c % 7 + 1,
                    self.create_sample_line(
                        coverage=c,
                        sessionid=sessionid,
                    ),
                )
                c += 1
        second_file = EditableReportFile("second_file.py")
        first_report.append(first_file)
        first_report.append(second_file)

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
                ),
                (
                    7,
                    13,
                    None,
                    [[2, 6, None, None, None], [1, 13, None, None, None]],
                    None,
                    None,
                ),
            ]
        }
        return first_report

    def create_sample_line(self, *, coverage, sessionid=None):
        return ReportLine.create(
            coverage=coverage,
            sessions=[(LineSession(id=sessionid, coverage=coverage))],
        )

    def test_adjust_sessions_no_cf(self, sample_first_report):
        first_value = self.convert_report_to_better_readable(sample_first_report)
        current_yaml = UserYaml({})
        assert (
            clear_carryforward_sessions(
                sample_first_report, ["enterprise"], current_yaml
            )
            == set()
        )
        assert first_value == self.convert_report_to_better_readable(
            sample_first_report
        )

    def test_adjust_sessions_full_cf_only(self, sample_first_report):
        current_yaml = UserYaml(
            {
                "flag_management": {
                    "individual_flags": [{"name": "enterprise", "carryforward": True}]
                }
            }
        )
        assert clear_carryforward_sessions(
            sample_first_report, ["enterprise"], current_yaml
        ) == {0}

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
                    ),
                    (
                        2,
                        15,
                        None,
                        [[1, 1, None, None, None], [3, 15, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        3,
                        9,
                        None,
                        [[2, 2, None, None, None], [1, 9, None, None, None]],
                        None,
                        None,
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
                    ),
                    (
                        5,
                        18,
                        None,
                        [[3, 11, None, None, None], [2, 18, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        6,
                        19,
                        None,
                        [[1, 5, None, None, None], [3, 19, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        7,
                        13,
                        None,
                        [[2, 6, None, None, None], [1, 13, None, None, None]],
                        None,
                        None,
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
