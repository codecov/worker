import json
import pprint
from asyncio import Future
from decimal import Decimal

import mock
import pytest
from celery.exceptions import SoftTimeLimitExceeded
from shared.reports.enums import UploadState
from shared.reports.resources import Report, ReportFile, Session, SessionType
from shared.reports.types import ReportLine, ReportTotals, SessionTotalsArray
from shared.torngit.exceptions import TorngitRateLimitError
from shared.yaml import UserYaml

from database.models import CommitReport, ReportDetails, RepositoryFlag, Upload
from database.tests.factories import (
    CommitFactory,
    ReportDetailsFactory,
    ReportFactory,
    ReportLevelTotalsFactory,
    RepositoryFlagFactory,
    UploadFactory,
    UploadLevelTotalsFactory,
)
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.labels import SpecialLabelsEnum
from services.archive import ArchiveService
from services.report import (
    NotReadyToBuildReportYetError,
    ProcessingError,
    ProcessingResult,
    ReportService,
)
from services.report import log as report_log
from services.report.raw_upload_processor import (
    SessionAdjustmentResult,
    _adjust_sessions,
)
from test_utils.base import BaseTestCase


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
        _report_json={"sessions": sessions_dict, "files": file_headers}
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
def sample_commit_with_report_big_with_labels(dbsession, mock_storage):
    sessions_dict = {
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
        },
    }
    file_headers = {
        "file_00.py": [
            0,
            [0, 4, 0, 4, 0, "0", 0, 0, 0, 0, 0, 0, 0],
            [[0, 4, 0, 4, 0, "0", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_01.py": [
            1,
            [0, 32, 32, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
            [[0, 32, 32, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
    }
    commit = CommitFactory.create(
        _report_json={"sessions": sessions_dict, "files": file_headers}
    )
    dbsession.add(commit)
    dbsession.flush()
    with open("tasks/tests/samples/sample_chunks_with_header.txt") as f:
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
        _report_json={"sessions": sessions_dict, "files": file_headers}
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
    @pytest.mark.asyncio
    async def test_build_report_from_commit_no_report_saved(self, dbsession, mocker):
        commit = CommitFactory(_report_json=None)
        dbsession.add(commit)
        dbsession.commit()
        res = await ReportService({}).build_report_from_commit(commit)
        assert res is not None
        assert res.files == []
        assert tuple(res.totals) == (0, 0, 0, 0, 0, None, 0, 0, 0, 0, 0, 0, 0)

    @pytest.mark.asyncio
    async def test_build_report_from_commit(self, dbsession, mock_storage):
        commit = CommitFactory(_report_json=None)
        dbsession.add(commit)
        report = ReportFactory(commit=commit)
        dbsession.add(report)

        details = ReportDetailsFactory(
            report=report,
            _files_array=[
                {
                    "filename": "awesome/__init__.py",
                    "file_index": 2,
                    "file_totals": [0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0],
                    "session_totals": [
                        [0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0]
                    ],
                    "diff_totals": [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                },
                {
                    "filename": "tests/__init__.py",
                    "file_index": 0,
                    "file_totals": [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    "session_totals": [
                        [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0]
                    ],
                    "diff_totals": None,
                },
                {
                    "filename": "tests/test_sample.py",
                    "file_index": 1,
                    "file_totals": [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    "session_totals": [[0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                    "diff_totals": None,
                },
            ],
        )
        dbsession.add(details)
        totals = ReportLevelTotalsFactory(
            report=report,
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=85.0,
            branches=0,
            methods=0,
        )
        dbsession.add(totals)

        upload = UploadFactory(report=report, order_number=0, upload_type="upload")
        dbsession.add(upload)
        upload_totals = UploadLevelTotalsFactory(
            upload=upload,
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=85.0,
            branches=0,
            methods=0,
        )
        dbsession.add(upload_totals)
        dbsession.commit()
        dbsession.flush()

        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)

        report = await ReportService({}).build_report_from_commit(commit)
        assert report is not None
        assert report.files == [
            "awesome/__init__.py",
            "tests/__init__.py",
            "tests/test_sample.py",
        ]
        assert report.totals == ReportTotals(
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=Decimal("85.00"),
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )

        assert len(report.sessions) == 1
        assert report.sessions[0].flags == []
        assert report.sessions[0].session_type == SessionType.uploaded
        assert report.sessions[0].totals == ReportTotals(
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=Decimal("85.00"),
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )

        # make sure report is still serializable
        ReportService({}).save_report(commit, report)

    @pytest.mark.asyncio
    async def test_build_report_from_commit_with_flags(self, dbsession, mock_storage):
        commit = CommitFactory(_report_json=None)
        dbsession.add(commit)
        report = ReportFactory(commit=commit)
        dbsession.add(report)

        details = ReportDetailsFactory(
            report=report,
            _files_array=[
                {
                    "filename": "awesome/__init__.py",
                    "file_index": 2,
                    "file_totals": [0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0],
                    "session_totals": [
                        [0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0]
                    ],
                    "diff_totals": [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                },
                {
                    "filename": "tests/__init__.py",
                    "file_index": 0,
                    "file_totals": [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    "session_totals": [
                        [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0]
                    ],
                    "diff_totals": None,
                },
                {
                    "filename": "tests/test_sample.py",
                    "file_index": 1,
                    "file_totals": [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    "session_totals": [[0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                    "diff_totals": None,
                },
            ],
        )
        dbsession.add(details)
        totals = ReportLevelTotalsFactory(
            report=report,
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=85.0,
            branches=0,
            methods=0,
        )
        dbsession.add(totals)

        flag1 = RepositoryFlagFactory(
            repository=commit.repository,
            flag_name="unit",
        )
        dbsession.add(flag1)
        flag2 = RepositoryFlagFactory(
            repository=commit.repository,
            flag_name="integration",
        )
        dbsession.add(flag2)
        flag3 = RepositoryFlagFactory(
            repository=commit.repository,
            flag_name="labels-flag",
        )
        dbsession.add(flag3)

        upload1 = UploadFactory(
            report=report, flags=[flag1], order_number=0, upload_type="upload"
        )
        dbsession.add(upload1)
        upload_totals1 = UploadLevelTotalsFactory(
            upload=upload1,
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=85.0,
            branches=0,
            methods=0,
        )
        dbsession.add(upload_totals1)
        dbsession.commit()

        upload2 = UploadFactory(
            report=report, flags=[flag1], order_number=1, upload_type="carriedforward"
        )
        dbsession.add(upload2)
        upload_totals2 = UploadLevelTotalsFactory(
            upload=upload2,
            files=3,
            lines=20,
            hits=20,
            misses=0,
            partials=0,
            coverage=100.0,
            branches=0,
            methods=0,
        )
        dbsession.add(upload_totals2)
        dbsession.commit()

        upload3 = UploadFactory(
            report=report, flags=[flag2], order_number=2, upload_type="carriedforward"
        )
        dbsession.add(upload3)
        upload_totals3 = UploadLevelTotalsFactory(
            upload=upload3,
            files=3,
            lines=20,
            hits=20,
            misses=0,
            partials=0,
            coverage=100.0,
            branches=0,
            methods=0,
        )
        dbsession.add(upload_totals3)
        dbsession.commit()
        dbsession.flush()

        upload4 = UploadFactory(
            report=report, flags=[flag3], order_number=3, upload_type="upload"
        )
        dbsession.add(upload4)
        upload_totals4 = UploadLevelTotalsFactory(
            upload=upload4,
            files=3,
            lines=20,
            hits=20,
            misses=0,
            partials=0,
            coverage=100.0,
            branches=0,
            methods=0,
        )
        dbsession.add(upload_totals4)
        dbsession.commit()
        dbsession.flush()

        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)

        yaml = {
            "flag_management": {
                "individual_flags": [
                    {
                        "name": "labels-flag",
                        "carryforward": True,
                        "carryforward_mode": "labels",
                    }
                ]
            }
        }
        report = await ReportService(yaml).build_report_from_commit(commit)
        assert report is not None
        assert report.files == [
            "awesome/__init__.py",
            "tests/__init__.py",
            "tests/test_sample.py",
        ]
        assert report.totals == ReportTotals(
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=Decimal("85.00"),
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )

        assert len(report.sessions) == 2
        assert report.sessions[0].flags == ["unit"]
        assert report.sessions[0].session_type == SessionType.uploaded
        assert report.sessions[0].totals == ReportTotals(
            files=3,
            lines=20,
            hits=17,
            misses=3,
            partials=0,
            coverage=Decimal("85.00"),
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        assert 1 not in report.sessions  # CF w/ equivalent direct upload
        assert report.sessions[2].flags == ["integration"]
        assert report.sessions[2].session_type == SessionType.carriedforward
        assert report.sessions[2].totals == ReportTotals(
            files=3,
            lines=20,
            hits=20,
            misses=0,
            partials=0,
            coverage=Decimal("100.00"),
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        assert 3 not in report.sessions  # labels flag w/ empty label set

        # make sure report is still serializable
        ReportService({}).save_report(commit, report)

    @pytest.mark.asyncio
    async def test_build_report_from_commit_fallback(
        self, dbsession, mocker, mock_storage
    ):
        commit = CommitFactory()
        dbsession.add(commit)
        dbsession.commit()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
        res = await ReportService({}).build_report_from_commit(commit)
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
