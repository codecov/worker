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
