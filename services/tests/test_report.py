import pytest
import pprint
from itertools import chain, combinations
from decimal import Decimal

from tests.base import BaseTestCase
from services.report import ReportService, NotReadyToBuildReportYetError
from database.tests.factories import CommitFactory, RepositoryFactory
from database.models import CommitReport, ReportDetails, Upload, RepositoryFlag
from services.archive import ArchiveService
from shared.reports.types import ReportTotals, ReportLine
from shared.reports.resources import ReportFile, Report, Session, SessionType
from shared.yaml import UserYaml


def powerset(iterable):
    "powerset([1,2,3]) --> () (1,) (2,) (3,) (1,2) (1,3) (2,3) (1,2,3)"
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(len(s) + 1))


@pytest.fixture
def sample_report():
    report = Report()
    first_file = ReportFile("file_1.go")
    first_file.append(
        1, ReportLine.create(coverage=1, sessions=[[0, 1]], complexity=(10, 2))
    )
    first_file.append(2, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    first_file.append(3, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(5, ReportLine.create(coverage=1, sessions=[[0, 1], [1, 1]]))
    first_file.append(6, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    first_file.append(8, ReportLine.create(coverage=1, sessions=[[0, 1], [1, 0]]))
    first_file.append(9, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(10, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    second_file = ReportFile("file_2.py")
    second_file.append(12, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    second_file.append(
        51, ReportLine.create(coverage="1/2", type="b", sessions=[[0, 1]])
    )
    report.append(first_file)
    report.append(second_file)
    report.add_session(
        Session(
            flags=["unit"],
            provider="circleci",
            session_type=SessionType.uploaded,
            build="aycaramba",
            totals=ReportTotals(2, 10),
        )
    )
    report.add_session(
        Session(
            flags=["integration"],
            provider="travis",
            session_type=SessionType.carriedforward,
            build="poli",
        )
    )
    return report


@pytest.fixture
def sample_commit_with_report_big(dbsession, mock_storage):
    sessions_dict = {
        "0": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": [],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
        "1": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["unit"],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
        "2": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["enterprise"],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
        "3": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["unit", "enterprise"],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
    }
    file_headers = {
        "file_00.py": [
            0,
            [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_01.py": [
            1,
            [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_10.py": [
            10,
            [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_11.py": [
            11,
            [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_12.py": [
            12,
            [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_13.py": [
            13,
            [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_14.py": [
            14,
            [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_02.py": [
            2,
            [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_03.py": [
            3,
            [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_04.py": [
            4,
            [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_05.py": [
            5,
            [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_06.py": [
            6,
            [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_07.py": [
            7,
            [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_08.py": [
            8,
            [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_09.py": [
            9,
            [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
    }
    commit = CommitFactory.create(
        report_json={"sessions": sessions_dict, "files": file_headers}
    )
    dbsession.add(commit)
    dbsession.flush()
    with open("tasks/tests/samples/sample_chunks_4_sessions.txt") as f:
        content = f.read().encode()
        archive_hash = ArchiveService.get_archive_hash(commit.repository)
        chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
        mock_storage.write_file("archive", chunks_url, content)
    return commit


@pytest.fixture
def sample_commit_with_report_big_already_carriedforward(dbsession, mock_storage):
    sessions_dict = {
        "0": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": [],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
        "1": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["unit"],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
        "2": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["enterprise"],
            "j": None,
            "n": None,
            "p": None,
            "st": "carriedforward",
            "t": None,
            "u": None,
        },
        "3": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["unit", "enterprise"],
            "j": None,
            "n": None,
            "p": None,
            "st": "carriedforward",
            "t": None,
            "u": None,
        },
    }
    file_headers = {
        "file_00.py": [
            0,
            [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_01.py": [
            1,
            [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_10.py": [
            10,
            [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_11.py": [
            11,
            [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_12.py": [
            12,
            [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_13.py": [
            13,
            [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_14.py": [
            14,
            [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_02.py": [
            2,
            [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_03.py": [
            3,
            [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_04.py": [
            4,
            [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_05.py": [
            5,
            [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_06.py": [
            6,
            [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_07.py": [
            7,
            [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_08.py": [
            8,
            [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_09.py": [
            9,
            [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
    }
    commit = CommitFactory.create(
        report_json={"sessions": sessions_dict, "files": file_headers}
    )
    dbsession.add(commit)
    dbsession.flush()
    with open("tasks/tests/samples/sample_chunks_4_sessions.txt") as f:
        content = f.read().encode()
        archive_hash = ArchiveService.get_archive_hash(commit.repository)
        chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
        mock_storage.write_file("archive", chunks_url, content)
    return commit


class TestReportService(BaseTestCase):
    def test_build_report_from_commit_no_report_saved(self, mocker):
        commit = CommitFactory.create(report_json=None)
        res = ReportService({}).build_report_from_commit(commit)
        assert res is not None
        assert res.files == []
        assert tuple(res.totals) == (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    def test_build_report_from_commit(self, mocker, mock_storage):
        commit = CommitFactory.create()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
        res = ReportService({}).build_report_from_commit(commit)
        assert res is not None
        assert res.files == [
            "awesome/__init__.py",
            "tests/__init__.py",
            "tests/test_sample.py",
        ]
        assert res.totals == ReportTotals(
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage="85.00000",
            branches=0,
            methods=0,
            messages=0,
            sessions=1,
            complexity=0,
            complexity_total=0,
            diff=[1, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
        )
        res._totals = None
        assert res.totals.files == 3
        assert res.totals.lines == 20
        assert res.totals.hits == 17
        assert res.totals.misses == 3
        assert res.totals.partials == 0
        assert res.totals.coverage == "85.00000"
        assert res.totals.branches == 0
        assert res.totals.methods == 0
        assert res.totals.messages == 0
        assert res.totals.sessions == 1
        assert res.totals.complexity == 0
        assert res.totals.complexity_total == 0
        # notice we dont compare the diff since that one comes from git information we lost on the reset

    def test_create_new_report_for_commit(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == sorted(
            [
                "file_00.py",
                "file_01.py",
                "file_02.py",
                "file_03.py",
                "file_04.py",
                "file_05.py",
                "file_06.py",
                "file_07.py",
                "file_08.py",
                "file_09.py",
                "file_10.py",
                "file_11.py",
                "file_12.py",
                "file_13.py",
                "file_14.py",
            ]
        )
        assert report.totals == ReportTotals(
            files=15,
            lines=188,
            hits=68,
            misses=26,
            partials=94,
            coverage="36.17021",
            branches=0,
            methods=0,
            messages=0,
            sessions=2,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        readable_report = self.convert_report_to_better_readable(report)
        expected_results = {
            "archive": {
                "file_00.py": [
                    (1, 1, None, [[2, 1, None, None, None]], None, None),
                    (2, 1, None, [[2, 1, None, None, None]], None, None),
                    (3, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (4, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (5, 0, None, [[3, 0, None, None, None]], None, None),
                    (6, 0, None, [[2, 0, None, None, None]], None, None),
                    (7, 0, None, [[3, 0, None, None, None]], None, None),
                    (8, 0, None, [[3, 0, None, None, None]], None, None),
                    (
                        9,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (10, 0, None, [[2, 0, None, None, None]], None, None),
                    (11, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (
                        12,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_01.py": [
                    (
                        2,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (3, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (
                        5,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        6,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        7,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (8, 1, None, [[2, 1, None, None, None]], None, None),
                    (9, 1, None, [[2, 1, None, None, None]], None, None),
                    (
                        10,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_02.py": [
                    (1, 1, None, [[2, 1, None, None, None]], None, None),
                    (2, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        4,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (5, 1, None, [[3, 1, None, None, None]], None, None),
                    (6, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (8, 1, None, [[2, 1, None, None, None]], None, None),
                    (
                        9,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (11, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (
                        12,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_03.py": [
                    (
                        2,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (3, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (4, 0, None, [[3, 0, None, None, None]], None, None),
                    (5, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (6, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        7,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (8, 0, None, [[3, 0, None, None, None]], None, None),
                    (9, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (10, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (11, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (12, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (
                        13,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (14, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (
                        15,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        16,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_04.py": [
                    (1, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (2, 0, None, [[3, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (
                        5,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (
                        7,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        8,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (10, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                ],
                "file_05.py": [
                    (2, 0, None, [[2, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (4, 0, None, [[3, 0, None, None, None]], None, None),
                    (5, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        6,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (
                        10,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_06.py": [
                    (3, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (4, 1, None, [[3, 1, None, None, None]], None, None),
                    (5, 1, None, [[3, 1, None, None, None]], None, None),
                    (6, 1, None, [[2, 1, None, None, None]], None, None),
                    (7, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        8,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_07.py": [
                    (1, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        2,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (3, 1, None, [[2, 1, None, None, None]], None, None),
                    (
                        4,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        5,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, 0, None, [[2, 0, None, None, None]], None, None),
                    (7, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (
                        10,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_08.py": [
                    (1, 0, None, [[3, 0, None, None, None]], None, None),
                    (2, 0, None, [[2, 0, None, None, None]], None, None),
                    (3, 0, None, [[2, 0, None, None, None]], None, None),
                    (4, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (5, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (6, 0, None, [[2, 0, None, None, None]], None, None),
                    (
                        7,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        8,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (
                        10,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_09.py": [
                    (1, 0, None, [[2, 0, None, None, None]], None, None),
                    (3, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        6,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (8, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (9, 1, None, [[2, 1, None, None, None]], None, None),
                    (
                        10,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (11, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (12, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        13,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_10.py": [
                    (2, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        3,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (4, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (
                        6,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (7, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_11.py": [
                    (1, 0, None, [[3, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (5, 0, None, [[2, 0, None, None, None]], None, None),
                    (6, 0, None, [[3, 0, None, None, None]], None, None),
                    (7, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (8, 1, None, [[2, 1, None, None, None]], None, None),
                    (9, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        11,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (12, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        13,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (15, 0, None, [[2, 0, None, None, None]], None, None),
                    (
                        16,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (19, 0, None, [[3, 0, None, None, None]], None, None),
                    (20, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        21,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_12.py": [
                    (2, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (3, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (4, 0, None, [[2, 0, None, None, None]], None, None),
                    (5, 0, None, [[3, 0, None, None, None]], None, None),
                    (7, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (10, 0, None, [[3, 0, None, None, None]], None, None),
                    (11, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        12,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_13.py": [
                    (2, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        6,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (14, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        15,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_14.py": [
                    (1, 1, None, [[2, 1, None, None, None]], None, None),
                    (2, 0, None, [[2, 0, None, None, None]], None, None),
                    (
                        3,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        5,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (7, 1, None, [[2, 1, None, None, None]], None, None),
                    (8, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (9, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[2, 1, None, None, None]], None, None),
                    (
                        11,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (14, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (15, 0, None, [[2, 0, None, None, None]], None, None),
                    (
                        16,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        19,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        20,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        21,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                ],
            },
            "report": {
                "files": {
                    "file_00.py": [
                        0,
                        [0, 14, 4, 5, 5, "28.57143", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_01.py": [
                        1,
                        [0, 10, 3, 0, 7, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_02.py": [
                        2,
                        [0, 11, 5, 0, 6, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_03.py": [
                        3,
                        [0, 15, 4, 2, 9, "26.66667", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_04.py": [
                        4,
                        [0, 10, 3, 1, 6, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_05.py": [
                        5,
                        [0, 13, 3, 2, 8, "23.07692", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_06.py": [
                        6,
                        [0, 7, 5, 0, 2, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_07.py": [
                        7,
                        [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_08.py": [
                        8,
                        [0, 11, 2, 4, 5, "18.18182", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_09.py": [
                        9,
                        [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_10.py": [
                        10,
                        [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_11.py": [
                        11,
                        [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_12.py": [
                        12,
                        [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_13.py": [
                        13,
                        [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_14.py": [
                        14,
                        [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                },
                "sessions": {
                    "2": {
                        "a": None,
                        "c": None,
                        "d": None,
                        "e": None,
                        "f": ["enterprise"],
                        "j": None,
                        "N": "Carriedforward",
                        "n": None,
                        "p": None,
                        "se": {"carriedforward_from": parent_commit.commitid},
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                    "3": {
                        "a": None,
                        "c": None,
                        "d": None,
                        "e": None,
                        "f": ["unit", "enterprise"],
                        "j": None,
                        "N": "Carriedforward",
                        "n": None,
                        "p": None,
                        "se": {"carriedforward_from": parent_commit.commitid},
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                },
            },
            "totals": {
                "b": 0,
                "c": "36.17021",
                "C": 0,
                "d": 0,
                "diff": None,
                "f": 15,
                "h": 68,
                "M": 0,
                "m": 26,
                "N": 0,
                "n": 188,
                "p": 94,
                "s": 2,
            },
        }
        assert (
            expected_results["report"]["sessions"]["2"]
            == readable_report["report"]["sessions"]["2"]
        )
        assert (
            expected_results["report"]["sessions"]["3"]
            == readable_report["report"]["sessions"]["3"]
        )
        assert (
            expected_results["report"]["sessions"]
            == readable_report["report"]["sessions"]
        )
        assert expected_results["report"]["files"] == readable_report["report"]["files"]
        assert expected_results["report"] == readable_report["report"]
        assert expected_results == readable_report

    def test_create_new_report_for_commit_is_called_as_generate(
        self, dbsession, mocker
    ):
        commit = CommitFactory.create(report_json=None)
        dbsession.add(commit)
        dbsession.flush()
        mocked_create_new_report_for_commit = mocker.patch.object(
            ReportService, "create_new_report_for_commit"
        )
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report_service = ReportService(UserYaml(yaml_dict))
        report = report_service.build_report_from_commit(commit)
        assert report == mocked_create_new_report_for_commit.return_value

    def test_build_report_from_commit_carriedforward_add_sessions(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert len(report.files) == 15
        report.add_session(Session(flags=["enterprise"]))
        readable_report = self.convert_report_to_better_readable(report)
        expected_results = {
            "archive": {},
            "report": {
                "files": {},
                "sessions": {
                    "0": {
                        "N": None,
                        "a": None,
                        "c": None,
                        "d": None,
                        "e": None,
                        "f": ["enterprise"],
                        "j": None,
                        "n": None,
                        "p": None,
                        "st": "uploaded",
                        "se": {},
                        "t": None,
                        "u": None,
                    }
                },
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": 0,
                "d": 0,
                "diff": None,
                "f": 0,
                "h": 0,
                "m": 0,
                "n": 0,
                "p": 0,
                "s": 1,
            },
        }
        pprint.pprint(readable_report)
        assert (
            readable_report["report"]["sessions"]["0"]
            == expected_results["report"]["sessions"]["0"]
        )
        assert (
            readable_report["report"]["sessions"]
            == expected_results["report"]["sessions"]
        )
        assert readable_report["report"] == expected_results["report"]
        assert readable_report == expected_results

    def test_build_report_from_commit_already_carriedforward_add_sessions(
        self, dbsession, sample_commit_with_report_big_already_carriedforward
    ):
        commit = sample_commit_with_report_big_already_carriedforward
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).build_report_from_commit(commit)
        assert report is not None
        assert len(report.files) == 15
        report.add_session(Session(flags=["enterprise"]))
        readable_report = self.convert_report_to_better_readable(report)
        sessions_dict = {
            "0": {
                "N": None,
                "a": None,
                "c": None,
                "d": None,
                "e": None,
                "f": None,
                "j": None,
                "n": None,
                "p": None,
                "st": "uploaded",
                "se": {},
                "t": None,
                "u": None,
            },
            "1": {
                "N": None,
                "a": None,
                "c": None,
                "d": None,
                "e": None,
                "f": ["unit"],
                "j": None,
                "n": None,
                "p": None,
                "st": "uploaded",
                "se": {},
                "t": None,
                "u": None,
            },
            "2": {
                "N": None,
                "a": None,
                "c": None,
                "d": None,
                "e": None,
                "f": ["enterprise"],
                "j": None,
                "n": None,
                "p": None,
                "st": "uploaded",
                "se": {},
                "t": None,
                "u": None,
            },
        }

        assert readable_report["report"]["sessions"]["0"] == sessions_dict["0"]
        assert readable_report["report"]["sessions"]["1"] == sessions_dict["1"]
        assert readable_report["report"]["sessions"]["2"] == sessions_dict["2"]
        assert readable_report["report"]["sessions"] == sessions_dict
        newly_added_session = {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["unit"],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "se": {},
            "t": None,
            "u": None,
        }
        report.add_session(Session(flags=["unit"]))
        new_readable_report = self.convert_report_to_better_readable(report)
        assert len(new_readable_report["report"]["sessions"]) == 4
        assert new_readable_report["report"]["sessions"]["0"] == sessions_dict["0"]
        assert new_readable_report["report"]["sessions"]["1"] == sessions_dict["1"]
        assert new_readable_report["report"]["sessions"]["2"] == sessions_dict["2"]
        assert new_readable_report["report"]["sessions"]["3"] == newly_added_session

    def test_create_new_report_for_commit_with_path_filters(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {
            "flags": {
                "enterprise": {"carryforward": True, "paths": ["file_1.*"]},
                "special_flag": {"paths": ["file_0.*"]},
            }
        }
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == sorted(
            ["file_10.py", "file_11.py", "file_12.py", "file_13.py", "file_14.py",]
        )
        assert report.totals == ReportTotals(
            files=5,
            lines=75,
            hits=29,
            misses=10,
            partials=36,
            coverage="38.66667",
            branches=0,
            methods=0,
            messages=0,
            sessions=2,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        readable_report = self.convert_report_to_better_readable(report)
        expected_results = {
            "archive": {
                "file_10.py": [
                    (2, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        3,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (4, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (
                        6,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (7, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_11.py": [
                    (1, 0, None, [[3, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (5, 0, None, [[2, 0, None, None, None]], None, None),
                    (6, 0, None, [[3, 0, None, None, None]], None, None),
                    (7, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (8, 1, None, [[2, 1, None, None, None]], None, None),
                    (9, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        11,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (12, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        13,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (15, 0, None, [[2, 0, None, None, None]], None, None),
                    (
                        16,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (19, 0, None, [[3, 0, None, None, None]], None, None),
                    (20, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        21,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_12.py": [
                    (2, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (3, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (4, 0, None, [[2, 0, None, None, None]], None, None),
                    (5, 0, None, [[3, 0, None, None, None]], None, None),
                    (7, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (10, 0, None, [[3, 0, None, None, None]], None, None),
                    (11, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (
                        12,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_13.py": [
                    (2, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        6,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "3/3",
                        None,
                        [[2, 1, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        1,
                        None,
                        [[3, 0, None, None, None], [2, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/3",
                        None,
                        [[2, 0, None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/2", None, [[3, "1/2", None, None, None]], None, None),
                    (14, 1, None, [[3, 1, None, None, None]], None, None),
                    (
                        15,
                        "2/2",
                        None,
                        [[3, 1, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_14.py": [
                    (1, 1, None, [[2, 1, None, None, None]], None, None),
                    (2, 0, None, [[2, 0, None, None, None]], None, None),
                    (
                        3,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        5,
                        "2/2",
                        None,
                        [[2, 1, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (7, 1, None, [[2, 1, None, None, None]], None, None),
                    (8, "1/3", None, [[2, "1/3", None, None, None]], None, None),
                    (9, "1/2", None, [[2, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[2, 1, None, None, None]], None, None),
                    (
                        11,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (14, "1/3", None, [[3, "1/3", None, None, None]], None, None),
                    (15, 0, None, [[2, 0, None, None, None]], None, None),
                    (
                        16,
                        "1/2",
                        None,
                        [[2, 0, None, None, None], [3, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/3",
                        None,
                        [[3, 0, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        19,
                        "1/2",
                        None,
                        [[3, 0, None, None, None], [2, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        20,
                        "3/3",
                        None,
                        [[3, 1, None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        21,
                        "1/2",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "1/2",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        1,
                        None,
                        [[2, 0, None, None, None], [3, 1, None, None, None]],
                        None,
                        None,
                    ),
                ],
            },
            "report": {
                "files": {
                    "file_10.py": [
                        10,
                        [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_11.py": [
                        11,
                        [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_12.py": [
                        12,
                        [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_13.py": [
                        13,
                        [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_14.py": [
                        14,
                        [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                },
                "sessions": {
                    "2": {
                        "a": None,
                        "c": None,
                        "d": None,
                        "e": None,
                        "f": ["enterprise"],
                        "j": None,
                        "N": "Carriedforward",
                        "n": None,
                        "p": None,
                        "se": {"carriedforward_from": parent_commit.commitid},
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                    "3": {
                        "a": None,
                        "c": None,
                        "d": None,
                        "e": None,
                        "f": ["unit", "enterprise"],
                        "j": None,
                        "N": "Carriedforward",
                        "n": None,
                        "p": None,
                        "se": {"carriedforward_from": parent_commit.commitid},
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                },
            },
            "totals": {
                "b": 0,
                "c": "38.66667",
                "C": 0,
                "d": 0,
                "diff": None,
                "f": 5,
                "h": 29,
                "M": 0,
                "m": 10,
                "N": 0,
                "n": 75,
                "p": 36,
                "s": 2,
            },
        }
        assert (
            expected_results["report"]["sessions"]["2"]
            == readable_report["report"]["sessions"]["2"]
        )
        assert (
            expected_results["report"]["sessions"]["3"]
            == readable_report["report"]["sessions"]["3"]
        )
        assert (
            expected_results["report"]["sessions"]
            == readable_report["report"]["sessions"]
        )
        assert expected_results["report"]["files"] == readable_report["report"]["files"]
        assert expected_results["report"] == readable_report["report"]
        assert expected_results["totals"] == readable_report["totals"]
        assert expected_results == readable_report

    def test_create_new_report_for_commit_no_flags(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {
            "flags": {
                "enterprise": {"paths": ["file_1.*"]},
                "special_flag": {"paths": ["file_0.*"]},
            }
        }
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == []
        assert report.totals == ReportTotals(
            files=0,
            lines=0,
            hits=0,
            misses=0,
            partials=0,
            coverage=0,
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        readable_report = self.convert_report_to_better_readable(report)
        expected_results = {
            "archive": {},
            "report": {"files": {}, "sessions": {},},
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": 0,
                "d": 0,
                "diff": None,
                "f": 0,
                "h": 0,
                "m": 0,
                "n": 0,
                "p": 0,
                "s": 0,
            },
        }
        assert (
            expected_results["report"]["sessions"]
            == readable_report["report"]["sessions"]
        )
        assert expected_results["report"]["files"] == readable_report["report"]["files"]
        assert expected_results["report"] == readable_report["report"]
        assert expected_results["totals"] == readable_report["totals"]
        assert expected_results == readable_report

    def test_create_new_report_for_commit_no_parent(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=None,
            report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == []
        assert report.totals == ReportTotals(
            files=0,
            lines=0,
            hits=0,
            misses=0,
            partials=0,
            coverage=0,
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        readable_report = self.convert_report_to_better_readable(report)
        expected_results = {
            "archive": {},
            "report": {"files": {}, "sessions": {},},
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": 0,
                "d": 0,
                "diff": None,
                "f": 0,
                "h": 0,
                "m": 0,
                "n": 0,
                "p": 0,
                "s": 0,
            },
        }
        assert (
            expected_results["report"]["sessions"]
            == readable_report["report"]["sessions"]
        )
        assert expected_results["report"]["files"] == readable_report["report"]["files"]
        assert expected_results["report"] == readable_report["report"]
        assert expected_results["totals"] == readable_report["totals"]
        assert expected_results == readable_report

    def test_create_new_report_for_commit_parent_not_ready(
        self, dbsession, sample_commit_with_report_big
    ):
        grandparent_commit = sample_commit_with_report_big
        parent_commit = CommitFactory.create(
            repository=grandparent_commit.repository,
            parent_commit_id=grandparent_commit.commitid,
            report_json=None,
            state="pending",
        )
        commit = CommitFactory.create(
            repository=grandparent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            report_json=None,
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == sorted(
            [
                "file_00.py",
                "file_01.py",
                "file_02.py",
                "file_03.py",
                "file_04.py",
                "file_05.py",
                "file_06.py",
                "file_07.py",
                "file_08.py",
                "file_09.py",
                "file_10.py",
                "file_11.py",
                "file_12.py",
                "file_13.py",
                "file_14.py",
            ]
        )
        assert report.totals == ReportTotals(
            files=15,
            lines=188,
            hits=68,
            misses=26,
            partials=94,
            coverage="36.17021",
            branches=0,
            methods=0,
            messages=0,
            sessions=2,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        readable_report = self.convert_report_to_better_readable(report)
        expected_results_report = {
            "files": {
                "file_00.py": [
                    0,
                    [0, 14, 4, 5, 5, "28.57143", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_01.py": [
                    1,
                    [0, 10, 3, 0, 7, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_02.py": [
                    2,
                    [0, 11, 5, 0, 6, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_03.py": [
                    3,
                    [0, 15, 4, 2, 9, "26.66667", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_04.py": [
                    4,
                    [0, 10, 3, 1, 6, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_05.py": [
                    5,
                    [0, 13, 3, 2, 8, "23.07692", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_06.py": [
                    6,
                    [0, 7, 5, 0, 2, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_07.py": [
                    7,
                    [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_08.py": [
                    8,
                    [0, 11, 2, 4, 5, "18.18182", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_09.py": [
                    9,
                    [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_10.py": [
                    10,
                    [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_11.py": [
                    11,
                    [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_12.py": [
                    12,
                    [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_13.py": [
                    13,
                    [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "file_14.py": [
                    14,
                    [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                    [None, [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
            },
            "sessions": {
                "2": {
                    "a": None,
                    "c": None,
                    "d": None,
                    "e": None,
                    "f": ["enterprise"],
                    "j": None,
                    "N": "Carriedforward",
                    "n": None,
                    "p": None,
                    "se": {"carriedforward_from": grandparent_commit.commitid},
                    "st": "carriedforward",
                    "t": None,
                    "u": None,
                },
                "3": {
                    "a": None,
                    "c": None,
                    "d": None,
                    "e": None,
                    "f": ["unit", "enterprise"],
                    "j": None,
                    "N": "Carriedforward",
                    "n": None,
                    "p": None,
                    "se": {"carriedforward_from": grandparent_commit.commitid},
                    "st": "carriedforward",
                    "t": None,
                    "u": None,
                },
            },
        }
        assert (
            expected_results_report["sessions"]["2"]
            == readable_report["report"]["sessions"]["2"]
        )
        assert (
            expected_results_report["sessions"]["3"]
            == readable_report["report"]["sessions"]["3"]
        )
        assert (
            expected_results_report["sessions"] == readable_report["report"]["sessions"]
        )
        assert expected_results_report == readable_report["report"]

    def test_create_new_report_for_commit_parent_not_ready_but_skipped(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        parent_commit.state = "skipped"
        dbsession.flush()
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            report_json=None,
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == sorted(
            [
                "file_00.py",
                "file_01.py",
                "file_02.py",
                "file_03.py",
                "file_04.py",
                "file_05.py",
                "file_06.py",
                "file_07.py",
                "file_08.py",
                "file_09.py",
                "file_10.py",
                "file_11.py",
                "file_12.py",
                "file_13.py",
                "file_14.py",
            ]
        )
        assert report.totals == ReportTotals(
            files=15,
            lines=188,
            hits=68,
            misses=26,
            partials=94,
            coverage="36.17021",
            branches=0,
            methods=0,
            messages=0,
            sessions=2,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        readable_report = self.convert_report_to_better_readable(report)
        expected_results_report = {
            "sessions": {
                "2": {
                    "N": "Carriedforward",
                    "a": None,
                    "c": None,
                    "d": readable_report["report"]["sessions"]["2"]["d"],
                    "e": None,
                    "f": ["enterprise"],
                    "j": None,
                    "n": None,
                    "p": None,
                    "st": "carriedforward",
                    "se": {"carriedforward_from": parent_commit.commitid},
                    "t": None,
                    "u": None,
                },
                "3": {
                    "N": "Carriedforward",
                    "a": None,
                    "c": None,
                    "d": readable_report["report"]["sessions"]["3"]["d"],
                    "e": None,
                    "f": ["unit", "enterprise"],
                    "j": None,
                    "n": None,
                    "p": None,
                    "st": "carriedforward",
                    "se": {"carriedforward_from": parent_commit.commitid},
                    "t": None,
                    "u": None,
                },
            },
        }
        assert (
            expected_results_report["sessions"]["2"]
            == readable_report["report"]["sessions"]["2"]
        )
        assert (
            expected_results_report["sessions"]["3"]
            == readable_report["report"]["sessions"]["3"]
        )
        assert (
            expected_results_report["sessions"] == readable_report["report"]["sessions"]
        )

    def test_create_new_report_for_commit_too_many_ancestors_not_ready(
        self, dbsession, sample_commit_with_report_big
    ):
        grandparent_commit = sample_commit_with_report_big
        current_commit = grandparent_commit
        for i in range(10):
            current_commit = CommitFactory.create(
                repository=grandparent_commit.repository,
                parent_commit_id=current_commit.commitid,
                report_json=None,
                state="pending",
            )
            dbsession.add(current_commit)
        commit = CommitFactory.create(
            repository=grandparent_commit.repository,
            parent_commit_id=current_commit.commitid,
            report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == []
        readable_report = self.convert_report_to_better_readable(report)
        expected_results_report = {
            "files": {},
            "sessions": {},
        }
        assert expected_results_report == readable_report["report"]

    def test_create_new_report_parent_had_no_parent_and_pending(self, dbsession):
        current_commit = CommitFactory.create(parent_commit_id=None, state="pending",)
        dbsession.add(current_commit)
        for i in range(5):
            current_commit = CommitFactory.create(
                repository=current_commit.repository,
                parent_commit_id=current_commit.commitid,
                report_json=None,
                state="pending",
            )
            dbsession.add(current_commit)
        commit = CommitFactory.create(
            repository=current_commit.repository,
            parent_commit_id=current_commit.commitid,
            report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        with pytest.raises(NotReadyToBuildReportYetError):
            ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)

    def test_create_new_report_for_commit_potential_cf_but_not_real_cf(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        dbsession.flush()
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            report_json=None,
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {
            "flag_management": {
                "default_rules": {"carryforward": False},
                "individual_flags": [{"name": "banana", "carryforward": True}],
            }
        }
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report.is_empty()

    def test_create_new_report_for_commit_parent_has_no_report(
        self, mock_storage, dbsession
    ):
        parent = CommitFactory.create()
        dbsession.add(parent)
        dbsession.flush()
        commit = CommitFactory.create(
            parent_commit_id=parent.commitid, repository=parent.repository
        )
        dbsession.add(commit)
        dbsession.flush()
        report_service = ReportService(
            UserYaml({"flags": {"enterprise": {"carryforward": True}}})
        )
        r = report_service.create_new_report_for_commit(commit)
        assert r.files == []

    def test_save_full_report(self, dbsession, mock_storage, sample_report):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_)
        dbsession.add(report_details)
        dbsession.flush()
        report_service = ReportService({})
        res = report_service.save_full_report(commit, sample_report)
        storage_hash = report_service.get_archive_service(
            commit.repository
        ).storage_hash
        assert res == {
            "url": f"v4/repos/{storage_hash}/commits/{commit.commitid}/chunks.txt"
        }
        assert len(current_report_row.uploads) == 2
        first_upload = dbsession.query(Upload).filter_by(
            report_id=current_report_row.id_, provider="circleci"
        )[0]
        second_upload = dbsession.query(Upload).filter_by(
            report_id=current_report_row.id_, provider="travis"
        )[0]
        assert first_upload.build_code == "aycaramba"
        assert first_upload.build_url is None
        assert first_upload.env is None
        assert first_upload.job_code is None
        assert first_upload.name is None
        assert first_upload.provider == "circleci"
        assert first_upload.report_id == current_report_row.id_
        assert first_upload.state == "complete"
        assert first_upload.storage_path is None
        assert first_upload.order_number == 0
        assert len(first_upload.flags) == 1
        assert first_upload.flags[0].repository == commit.repository
        assert first_upload.flags[0].flag_name == "unit"
        assert first_upload.totals is not None
        assert first_upload.totals.branches == 0
        assert first_upload.totals.coverage == Decimal("0.0")
        assert first_upload.totals.hits == 0
        assert first_upload.totals.lines == 10
        assert first_upload.totals.methods == 0
        assert first_upload.totals.misses == 0
        assert first_upload.totals.partials == 0
        assert first_upload.totals.files == 2
        assert first_upload.upload_extras == {}
        assert first_upload.upload_type == "uploaded"
        assert second_upload.build_code == "poli"
        assert second_upload.build_url is None
        assert second_upload.env is None
        assert second_upload.job_code is None
        assert second_upload.name is None
        assert second_upload.provider == "travis"
        assert second_upload.report_id == current_report_row.id_
        assert second_upload.state == "complete"
        assert second_upload.storage_path is None
        assert second_upload.order_number == 1
        assert len(second_upload.flags) == 1
        assert second_upload.flags[0].repository == commit.repository
        assert second_upload.flags[0].flag_name == "integration"
        assert second_upload.totals is None
        assert second_upload.upload_extras == {}
        assert second_upload.upload_type == "carriedforward"
        assert report_details.files_array == [
            {
                "filename": "file_1.go",
                "file_index": 0,
                "file_totals": ReportTotals(
                    files=0,
                    lines=8,
                    hits=5,
                    misses=3,
                    partials=0,
                    coverage="62.50000",
                    branches=0,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=10,
                    complexity_total=2,
                    diff=0,
                ),
                "session_totals": [
                    ReportTotals(
                        files=0,
                        lines=8,
                        hits=5,
                        misses=3,
                        partials=0,
                        coverage="62.50000",
                        branches=0,
                        methods=0,
                        messages=0,
                        sessions=0,
                        complexity=10,
                        complexity_total=2,
                        diff=0,
                    )
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_2.py",
                "file_index": 1,
                "file_totals": ReportTotals(
                    files=0,
                    lines=2,
                    hits=1,
                    misses=0,
                    partials=1,
                    coverage="50.00000",
                    branches=1,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=0,
                    complexity_total=0,
                    diff=0,
                ),
                "session_totals": [
                    ReportTotals(
                        files=0,
                        lines=2,
                        hits=1,
                        misses=0,
                        partials=1,
                        coverage="50.00000",
                        branches=1,
                        methods=0,
                        messages=0,
                        sessions=0,
                        complexity=0,
                        complexity_total=0,
                        diff=0,
                    )
                ],
                "diff_totals": None,
            },
        ]

    def test_save_report(self, dbsession, mock_storage, sample_report):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_)
        dbsession.add(report_details)
        dbsession.flush()
        report_service = ReportService({})
        res = report_service.save_report(commit, sample_report)
        storage_hash = report_service.get_archive_service(
            commit.repository
        ).storage_hash
        assert res == {
            "url": f"v4/repos/{storage_hash}/commits/{commit.commitid}/chunks.txt"
        }
        assert len(current_report_row.uploads) == 0
        assert report_details.files_array == [
            {
                "filename": "file_1.go",
                "file_index": 0,
                "file_totals": ReportTotals(
                    files=0,
                    lines=8,
                    hits=5,
                    misses=3,
                    partials=0,
                    coverage="62.50000",
                    branches=0,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=10,
                    complexity_total=2,
                    diff=0,
                ),
                "session_totals": [
                    ReportTotals(
                        files=0,
                        lines=8,
                        hits=5,
                        misses=3,
                        partials=0,
                        coverage="62.50000",
                        branches=0,
                        methods=0,
                        messages=0,
                        sessions=0,
                        complexity=10,
                        complexity_total=2,
                        diff=0,
                    )
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_2.py",
                "file_index": 1,
                "file_totals": ReportTotals(
                    files=0,
                    lines=2,
                    hits=1,
                    misses=0,
                    partials=1,
                    coverage="50.00000",
                    branches=1,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=0,
                    complexity_total=0,
                    diff=0,
                ),
                "session_totals": [
                    ReportTotals(
                        files=0,
                        lines=2,
                        hits=1,
                        misses=0,
                        partials=1,
                        coverage="50.00000",
                        branches=1,
                        methods=0,
                        messages=0,
                        sessions=0,
                        complexity=0,
                        complexity_total=0,
                        diff=0,
                    )
                ],
                "diff_totals": None,
            },
        ]
        expected = {
            "files": {
                "file_1.go": [
                    0,
                    [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0],
                    [[0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0]],
                    None,
                ],
                "file_2.py": [
                    1,
                    [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                    [[0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "t": [2, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    "d": None,
                    "a": None,
                    "f": ["unit"],
                    "c": "circleci",
                    "n": "aycaramba",
                    "N": None,
                    "j": None,
                    "u": None,
                    "p": None,
                    "e": None,
                    "st": "uploaded",
                    "se": {},
                },
                "1": {
                    "t": None,
                    "d": None,
                    "a": None,
                    "f": ["integration"],
                    "c": "travis",
                    "n": "poli",
                    "N": None,
                    "j": None,
                    "u": None,
                    "p": None,
                    "e": None,
                    "st": "carriedforward",
                    "se": {},
                },
            },
        }
        assert (
            commit.report_json["sessions"]["0"]["t"] == expected["sessions"]["0"]["t"]
        )
        assert commit.report_json["sessions"]["0"] == expected["sessions"]["0"]
        assert commit.report_json["sessions"] == expected["sessions"]
        assert commit.report_json == expected
        assert res["url"] in mock_storage.storage["archive"]
        print(mock_storage.storage["archive"][res["url"]])
        expected_content = "\n".join(
            [
                "{}",
                "[1, null, [[0, 1]], null, [10, 2]]",
                "[0, null, [[0, 1]]]",
                "[1, null, [[0, 1]]]",
                "",
                "[1, null, [[0, 1], [1, 1]]]",
                "[0, null, [[0, 1]]]",
                "",
                "[1, null, [[0, 1], [1, 0]]]",
                "[1, null, [[0, 1]]]",
                "[0, null, [[0, 1]]]",
                "<<<<< end_of_chunk >>>>>",
                "{}",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "[1, null, [[0, 1]]]",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                '["1/2", "b", [[0, 1]]]',
            ]
        )
        assert mock_storage.storage["archive"][res["url"]].decode() == expected_content

    def test_initialize_and_save_report_brand_new(self, dbsession, mock_storage):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        report_service = ReportService({})
        r = report_service.initialize_and_save_report(commit)
        assert r is not None
        assert r.details is not None
        assert r.details.files_array == []
        assert len(mock_storage.storage["archive"]) == 0

    def test_initialize_and_save_report_report_but_no_details(
        self, dbsession, mock_storage
    ):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(report_row)
        dbsession.flush()
        report_service = ReportService({})
        r = report_service.initialize_and_save_report(commit)
        dbsession.refresh(report_row)
        assert r is not None
        assert r.details is not None
        assert r.details.files_array == []
        assert len(mock_storage.storage["archive"]) == 0

    def test_initialize_and_save_report_carryforward_needed(
        self, dbsession, sample_commit_with_report_big, mocker, mock_storage
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            report_json=None,
            parent_commit_id=parent_commit.commitid,
            repository=parent_commit.repository,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report_service = ReportService(UserYaml(yaml_dict))
        r = report_service.initialize_and_save_report(commit)
        assert len(r.uploads) == 2
        first_upload = dbsession.query(Upload).filter_by(
            report_id=r.id_, order_number=2
        )[0]
        second_upload = dbsession.query(Upload).filter_by(
            report_id=r.id_, order_number=3
        )[0]
        assert first_upload.build_code is None
        assert first_upload.build_url is None
        assert first_upload.env is None
        assert first_upload.job_code is None
        assert first_upload.name == "Carriedforward"
        assert first_upload.provider is None
        assert first_upload.report_id == r.id_
        assert first_upload.state == "complete"
        assert first_upload.storage_path is None
        assert first_upload.order_number == 2
        assert len(first_upload.flags) == 1
        assert first_upload.flags[0].repository == commit.repository
        assert first_upload.flags[0].flag_name == "enterprise"
        assert first_upload.totals is None
        assert first_upload.upload_extras == {
            "carriedforward_from": parent_commit.commitid
        }
        assert first_upload.upload_type == "carriedforward"
        assert second_upload.build_code is None
        assert second_upload.build_url is None
        assert second_upload.env is None
        assert second_upload.job_code is None
        assert second_upload.name == "Carriedforward"
        assert second_upload.provider is None
        assert second_upload.report_id == r.id_
        assert second_upload.state == "complete"
        assert second_upload.storage_path is None
        assert second_upload.order_number == 3
        assert len(second_upload.flags) == 2
        assert sorted([f.flag_name for f in second_upload.flags]) == [
            "enterprise",
            "unit",
        ]
        assert second_upload.totals is None
        assert second_upload.upload_extras == {
            "carriedforward_from": parent_commit.commitid
        }
        assert second_upload.upload_type == "carriedforward"
        assert r.details is not None
        assert sorted(f["filename"] for f in r.details.files_array) == [
            "file_00.py",
            "file_01.py",
            "file_02.py",
            "file_03.py",
            "file_04.py",
            "file_05.py",
            "file_06.py",
            "file_07.py",
            "file_08.py",
            "file_09.py",
            "file_10.py",
            "file_11.py",
            "file_12.py",
            "file_13.py",
            "file_14.py",
        ]

    def test_initialize_and_save_report_needs_backporting(
        self, dbsession, sample_commit_with_report_big, mock_storage
    ):
        commit = sample_commit_with_report_big
        report_service = ReportService({})
        r = report_service.initialize_and_save_report(commit)
        assert r is not None
        assert r.details is not None
        assert len(r.uploads) == 4
        first_upload = dbsession.query(Upload).filter_by(order_number=0).first()
        print(first_upload.flags)
        assert sorted([f.flag_name for f in first_upload.flags]) == []
        second_upload = dbsession.query(Upload).filter_by(order_number=1).first()
        assert sorted([f.flag_name for f in second_upload.flags]) == ["unit"]
        third_upload = dbsession.query(Upload).filter_by(order_number=2).first()
        assert sorted([f.flag_name for f in third_upload.flags]) == ["enterprise"]
        fourth_upload = dbsession.query(Upload).filter_by(order_number=3).first()
        assert sorted([f.flag_name for f in fourth_upload.flags]) == [
            "enterprise",
            "unit",
        ]
        assert (
            dbsession.query(RepositoryFlag)
            .filter_by(repository_id=commit.repoid)
            .count()
            == 2
        )
        assert r.details.files_array == [
            {
                "filename": "file_00.py",
                "file_index": 0,
                "file_totals": [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_01.py",
                "file_index": 1,
                "file_totals": [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_10.py",
                "file_index": 10,
                "file_totals": [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_11.py",
                "file_index": 11,
                "file_totals": [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_12.py",
                "file_index": 12,
                "file_totals": [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_13.py",
                "file_index": 13,
                "file_totals": [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_14.py",
                "file_index": 14,
                "file_totals": [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_02.py",
                "file_index": 2,
                "file_totals": [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_03.py",
                "file_index": 3,
                "file_totals": [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_04.py",
                "file_index": 4,
                "file_totals": [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_05.py",
                "file_index": 5,
                "file_totals": [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_06.py",
                "file_index": 6,
                "file_totals": [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_07.py",
                "file_index": 7,
                "file_totals": [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_08.py",
                "file_index": 8,
                "file_totals": [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
            {
                "filename": "file_09.py",
                "file_index": 9,
                "file_totals": [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                "session_totals": [
                    None,
                    None,
                    None,
                    [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                ],
                "diff_totals": None,
            },
        ]
        assert len(mock_storage.storage["archive"]) == 1

    def test_initialize_and_save_report_existing_report(
        self, mock_storage, sample_report, dbsession, mocker
    ):
        mocker_save_full_report = mocker.patch.object(ReportService, "save_full_report")
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_)
        dbsession.add(report_details)
        dbsession.flush()
        report_service = ReportService({})
        report_service.save_report(commit, sample_report)
        res = report_service.initialize_and_save_report(commit)
        assert res == current_report_row
        assert not mocker_save_full_report.called
