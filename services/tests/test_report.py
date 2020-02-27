import random
import pytest
import pprint
import json
from itertools import chain, combinations, permutations

from tests.base import BaseTestCase
from services.report import ReportService
from database.tests.factories import CommitFactory
from services.archive import ArchiveService
from covreports.reports.types import ReportTotals, LineSession, ReportLine
from covreports.reports.resources import ReportFile, Report, Session
from covreports.utils.merge import get_coverage_from_sessions


def powerset(iterable):
    "powerset([1,2,3]) --> () (1,) (2,) (3,) (1,2) (1,3) (2,3) (1,2,3)"
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(len(s) + 1))


def weird_report():
    filenames = ["file_%s.py" % n for n in range(15)]
    files = [ReportFile(fn) for fn in filenames]
    session_numbers = list(range(4))
    flags = ["unit", "enterprise"]
    flags = powerset(flags)
    sessions = [Session(flags=f) for f in flags]
    report = Report()
    for s in sessions:
        report.add_session(s)
    possible_coverages = [0, 1, "1/2", "1/3"]
    count = 0
    for pwsets in powerset(possible_coverages):
        if pwsets:
            for sn in permutations(session_numbers, len(pwsets)):
                sessions = [LineSession(coverage=i, id=p) for i, p in zip(pwsets, sn)]
                line = ReportLine(
                    coverage=get_coverage_from_sessions(sessions), sessions=sessions
                )
                file_to_add = random.randint(0, 14)
                files[file_to_add].append(len(files[file_to_add]._lines) + 1, line)
                count += 1
    for f in files:
        report.append(f)
    chunks = report.to_archive()
    totals, file_summaries = report.to_database()
    file_summaries = json.loads(file_summaries)
    pprint.pprint(totals)
    pprint.pprint(file_summaries["files"])
    pprint.pprint(file_summaries["sessions"])
    return chunks


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


class TestReportService(BaseTestCase):
    def test_build_report_from_commit_no_report_saved(self, mocker):
        commit = CommitFactory.create(report_json=None)
        res = ReportService().build_report_from_commit(commit)
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
        res = ReportService().build_report_from_commit(commit)
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
        res.reset()
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
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(yaml_dict).create_new_report_for_commit(commit, 1)
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
                    (1, 1, None, [[0, 1, None, None, None]], None, None),
                    (2, 1, None, [[0, 1, None, None, None]], None, None),
                    (3, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (4, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (5, 0, None, [[1, 0, None, None, None]], None, None),
                    (6, 0, None, [[0, 0, None, None, None]], None, None),
                    (7, 0, None, [[1, 0, None, None, None]], None, None),
                    (8, 0, None, [[1, 0, None, None, None]], None, None),
                    (
                        9,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (10, 0, None, [[0, 0, None, None, None]], None, None),
                    (11, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (
                        12,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_01.py": [
                    (
                        2,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (3, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (
                        5,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        6,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        7,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (8, 1, None, [[0, 1, None, None, None]], None, None),
                    (9, 1, None, [[0, 1, None, None, None]], None, None),
                    (
                        10,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_02.py": [
                    (1, 1, None, [[0, 1, None, None, None]], None, None),
                    (2, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        4,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (5, 1, None, [[1, 1, None, None, None]], None, None),
                    (6, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (8, 1, None, [[0, 1, None, None, None]], None, None),
                    (
                        9,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (11, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (
                        12,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_03.py": [
                    (
                        2,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (3, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (4, 0, None, [[1, 0, None, None, None]], None, None),
                    (5, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (6, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        7,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (8, 0, None, [[1, 0, None, None, None]], None, None),
                    (9, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (10, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (11, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (12, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (
                        13,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (14, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (
                        15,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        16,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_04.py": [
                    (1, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (2, 0, None, [[1, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (
                        5,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (
                        7,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        8,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (10, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                ],
                "file_05.py": [
                    (2, 0, None, [[0, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (4, 0, None, [[1, 0, None, None, None]], None, None),
                    (5, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        6,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (
                        10,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_06.py": [
                    (3, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (4, 1, None, [[1, 1, None, None, None]], None, None),
                    (5, 1, None, [[1, 1, None, None, None]], None, None),
                    (6, 1, None, [[0, 1, None, None, None]], None, None),
                    (7, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        8,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_07.py": [
                    (1, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        2,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (3, 1, None, [[0, 1, None, None, None]], None, None),
                    (
                        4,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        5,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, 0, None, [[0, 0, None, None, None]], None, None),
                    (7, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (
                        10,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_08.py": [
                    (1, 0, None, [[1, 0, None, None, None]], None, None),
                    (2, 0, None, [[0, 0, None, None, None]], None, None),
                    (3, 0, None, [[0, 0, None, None, None]], None, None),
                    (4, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (5, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (6, 0, None, [[0, 0, None, None, None]], None, None),
                    (
                        7,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        8,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (9, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (
                        10,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_09.py": [
                    (1, 0, None, [[0, 0, None, None, None]], None, None),
                    (3, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        6,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (8, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (9, 1, None, [[0, 1, None, None, None]], None, None),
                    (
                        10,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (11, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (12, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        13,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_10.py": [
                    (2, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        3,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (4, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (
                        6,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (7, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_11.py": [
                    (1, 0, None, [[1, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (5, 0, None, [[0, 0, None, None, None]], None, None),
                    (6, 0, None, [[1, 0, None, None, None]], None, None),
                    (7, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (8, 1, None, [[0, 1, None, None, None]], None, None),
                    (9, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        11,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (12, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        13,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (15, 0, None, [[0, 0, None, None, None]], None, None),
                    (
                        16,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (19, 0, None, [[1, 0, None, None, None]], None, None),
                    (20, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        21,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_12.py": [
                    (2, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (3, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (4, 0, None, [[0, 0, None, None, None]], None, None),
                    (5, 0, None, [[1, 0, None, None, None]], None, None),
                    (7, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (10, 0, None, [[1, 0, None, None, None]], None, None),
                    (11, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        12,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_13.py": [
                    (2, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        6,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (14, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        15,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_14.py": [
                    (1, 1, None, [[0, 1, None, None, None]], None, None),
                    (2, 0, None, [[0, 0, None, None, None]], None, None),
                    (
                        3,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        5,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (7, 1, None, [[0, 1, None, None, None]], None, None),
                    (8, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (9, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[0, 1, None, None, None]], None, None),
                    (
                        11,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (14, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (15, 0, None, [[0, 0, None, None, None]], None, None),
                    (
                        16,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        19,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        20,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        21,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
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
                        [None, [0, 14, 4, 5, 5, "28.57143", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_01.py": [
                        1,
                        [0, 10, 3, 0, 7, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 10, 3, 0, 7, "30.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_02.py": [
                        7,
                        [0, 11, 5, 0, 6, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 5, 0, 6, "45.45455", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_03.py": [
                        8,
                        [0, 15, 4, 2, 9, "26.66667", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 15, 4, 2, 9, "26.66667", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_04.py": [
                        9,
                        [0, 10, 3, 1, 6, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 10, 3, 1, 6, "30.00000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_05.py": [
                        10,
                        [0, 13, 3, 2, 8, "23.07692", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 13, 3, 2, 8, "23.07692", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_06.py": [
                        11,
                        [0, 7, 5, 0, 2, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 7, 5, 0, 2, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_07.py": [
                        12,
                        [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_08.py": [
                        13,
                        [0, 11, 2, 4, 5, "18.18182", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 2, 4, 5, "18.18182", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_09.py": [
                        14,
                        [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_10.py": [
                        2,
                        [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_11.py": [
                        3,
                        [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_12.py": [
                        4,
                        [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_13.py": [
                        5,
                        [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_14.py": [
                        6,
                        [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                },
                "sessions": {
                    "0": {
                        "N": "Carriedforward",
                        "a": None,
                        "c": None,
                        "d": readable_report["report"]["sessions"]["0"]["d"],
                        "e": None,
                        "f": ["enterprise"],
                        "j": None,
                        "n": None,
                        "p": None,
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                    "1": {
                        "N": "Carriedforward",
                        "a": None,
                        "c": None,
                        "d": readable_report["report"]["sessions"]["1"]["d"],
                        "e": None,
                        "f": ["unit", "enterprise"],
                        "j": None,
                        "n": None,
                        "p": None,
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                },
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": "36.17021",
                "d": 0,
                "diff": None,
                "f": 15,
                "h": 68,
                "m": 26,
                "n": 188,
                "p": 94,
                "s": 2,
            },
        }
        assert expected_results["report"]["sessions"]["0"] == readable_report["report"]["sessions"]["0"]
        assert expected_results["report"]["sessions"] == readable_report["report"]["sessions"]
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
        report_service = ReportService(yaml_dict)
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
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(yaml_dict).create_new_report_for_commit(commit, 1)
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
        assert readable_report == expected_results

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
        yaml_dict = {
            "flags": {
                "enterprise": {"carryforward": True, "paths": ["file_1.*"]},
                "special_flag": {"paths": ["file_0.*"]},
            }
        }
        report = ReportService(yaml_dict).create_new_report_for_commit(commit, 1)
        assert report is not None
        assert sorted(report.files) == sorted(
            [
                "file_10.py",
                "file_11.py",
                "file_12.py",
                "file_13.py",
                "file_14.py",
            ]
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
                    (2, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        3,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (4, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (
                        6,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (7, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_11.py": [
                    (1, 0, None, [[1, 0, None, None, None]], None, None),
                    (3, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (4, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (5, 0, None, [[0, 0, None, None, None]], None, None),
                    (6, 0, None, [[1, 0, None, None, None]], None, None),
                    (7, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (8, 1, None, [[0, 1, None, None, None]], None, None),
                    (9, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        11,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (12, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        13,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (15, 0, None, [[0, 0, None, None, None]], None, None),
                    (
                        16,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (19, 0, None, [[1, 0, None, None, None]], None, None),
                    (20, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        21,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_12.py": [
                    (2, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (3, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (4, 0, None, [[0, 0, None, None, None]], None, None),
                    (5, 0, None, [[1, 0, None, None, None]], None, None),
                    (7, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        8,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (10, 0, None, [[1, 0, None, None, None]], None, None),
                    (11, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (
                        12,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        14,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_13.py": [
                    (2, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        6,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (7, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (
                        8,
                        "3/3",
                        None,
                        [[0, 1, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        9,
                        1,
                        None,
                        [[1, 0, None, None, None], [0, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (
                        10,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        11,
                        "1/3",
                        None,
                        [[0, 0, None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/2", None, [[1, "1/2", None, None, None]], None, None),
                    (14, 1, None, [[1, 1, None, None, None]], None, None),
                    (
                        15,
                        "2/2",
                        None,
                        [[1, 1, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                ],
                "file_14.py": [
                    (1, 1, None, [[0, 1, None, None, None]], None, None),
                    (2, 0, None, [[0, 0, None, None, None]], None, None),
                    (
                        3,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        5,
                        "2/2",
                        None,
                        [[0, 1, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (6, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (7, 1, None, [[0, 1, None, None, None]], None, None),
                    (8, "1/3", None, [[0, "1/3", None, None, None]], None, None),
                    (9, "1/2", None, [[0, "1/2", None, None, None]], None, None),
                    (10, 1, None, [[0, 1, None, None, None]], None, None),
                    (
                        11,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        12,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                    (13, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (14, "1/3", None, [[1, "1/3", None, None, None]], None, None),
                    (15, 0, None, [[0, 0, None, None, None]], None, None),
                    (
                        16,
                        "1/2",
                        None,
                        [[0, 0, None, None, None], [1, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        17,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        18,
                        "1/3",
                        None,
                        [[1, 0, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        19,
                        "1/2",
                        None,
                        [[1, 0, None, None, None], [0, "1/2", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        20,
                        "3/3",
                        None,
                        [[1, 1, None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        21,
                        "1/2",
                        None,
                        [[0, "1/2", None, None, None], [1, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "1/2",
                        None,
                        [[1, "1/2", None, None, None], [0, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        23,
                        1,
                        None,
                        [[0, 0, None, None, None], [1, 1, None, None, None]],
                        None,
                        None,
                    ),
                ],
            },
            "report": {
                "files": {
                    "file_10.py": [
                        0,
                        [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_11.py": [
                        1,
                        [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_12.py": [
                        2,
                        [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_13.py": [
                        3,
                        [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "file_14.py": [
                        4,
                        [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        [None, [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                },
                "sessions": {
                    "0": {
                        "N": "Carriedforward",
                        "a": None,
                        "c": None,
                        "d": readable_report["report"]["sessions"]["0"]["d"],
                        "e": None,
                        "f": ["enterprise"],
                        "j": None,
                        "n": None,
                        "p": None,
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                    "1": {
                        "N": "Carriedforward",
                        "a": None,
                        "c": None,
                        "d": readable_report["report"]["sessions"]["1"]["d"],
                        "e": None,
                        "f": ["unit", "enterprise"],
                        "j": None,
                        "n": None,
                        "p": None,
                        "st": "carriedforward",
                        "t": None,
                        "u": None,
                    },
                },
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": "38.66667",
                "d": 0,
                "diff": None,
                "f": 5,
                "h": 29,
                "m": 10,
                "n": 75,
                "p": 36,
                "s": 2,
            },
        }
        assert expected_results["report"]["sessions"]["0"] == readable_report["report"]["sessions"]["0"]
        assert expected_results["report"]["sessions"] == readable_report["report"]["sessions"]
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
        report = ReportService(yaml_dict).create_new_report_for_commit(commit, 1)
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
            "report": {
                "files": {},
                "sessions": {},
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
                "s": 0,
            },
        }
        assert expected_results["report"]["sessions"] == readable_report["report"]["sessions"]
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
        yaml_dict = {
            "flags": {
                "enterprise": {"paths": ["file_1.*"]},
                "special_flag": {"paths": ["file_0.*"]},
            }
        }
        report = ReportService(yaml_dict).create_new_report_for_commit(commit, 1)
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
            "report": {
                "files": {},
                "sessions": {},
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
                "s": 0,
            },
        }
        assert expected_results["report"]["sessions"] == readable_report["report"]["sessions"]
        assert expected_results["report"]["files"] == readable_report["report"]["files"]
        assert expected_results["report"] == readable_report["report"]
        assert expected_results["totals"] == readable_report["totals"]
        assert expected_results == readable_report
