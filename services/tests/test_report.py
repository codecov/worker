from asyncio import Future
from decimal import Decimal

import mock
import pytest
from celery.exceptions import SoftTimeLimitExceeded
from shared.reports.enums import UploadState
from shared.reports.resources import Report, ReportFile, Session, SessionType
from shared.reports.types import ReportLine, ReportTotals
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
            None,
        ],
        "file_01.py": [
            1,
            [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_10.py": [
            10,
            [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_11.py": [
            11,
            [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_12.py": [
            12,
            [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_13.py": [
            13,
            [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_14.py": [
            14,
            [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_02.py": [
            2,
            [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_03.py": [
            3,
            [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_04.py": [
            4,
            [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_05.py": [
            5,
            [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_06.py": [
            6,
            [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_07.py": [
            7,
            [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_08.py": [
            8,
            [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_09.py": [
            9,
            [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
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
            None,
        ],
        "file_01.py": [
            1,
            [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_10.py": [
            10,
            [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_11.py": [
            11,
            [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_12.py": [
            12,
            [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_13.py": [
            13,
            [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_14.py": [
            14,
            [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_02.py": [
            2,
            [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_03.py": [
            3,
            [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_04.py": [
            4,
            [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_05.py": [
            5,
            [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_06.py": [
            6,
            [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_07.py": [
            7,
            [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_08.py": [
            8,
            [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
            None,
        ],
        "file_09.py": [
            9,
            [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
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
    def test_build_report_from_commit_no_report_saved(self, dbsession, mocker):
        commit = CommitFactory(_report_json=None)
        dbsession.add(commit)
        dbsession.commit()
        res = ReportService({}).build_report_from_commit(commit)
        assert res is not None
        assert res.files == []
        assert tuple(res.totals) == (0, 0, 0, 0, 0, None, 0, 0, 0, 0, 0, 0, 0)

    def test_build_report_from_commit(self, dbsession, mock_storage):
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
                    "diff_totals": [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                },
                {
                    "filename": "tests/__init__.py",
                    "file_index": 0,
                    "file_totals": [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    "diff_totals": None,
                },
                {
                    "filename": "tests/test_sample.py",
                    "file_index": 1,
                    "file_totals": [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
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

        report = ReportService({}).build_report_from_commit(commit)
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

    def test_build_report_from_commit_with_flags(self, dbsession, mock_storage):
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
                    "diff_totals": [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                },
                {
                    "filename": "tests/__init__.py",
                    "file_index": 0,
                    "file_totals": [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    "diff_totals": None,
                },
                {
                    "filename": "tests/test_sample.py",
                    "file_index": 1,
                    "file_totals": [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
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
        report = ReportService(yaml).build_report_from_commit(commit)
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

    def test_build_report_from_commit_fallback(self, dbsession, mocker, mock_storage):
        commit = CommitFactory()
        dbsession.add(commit)
        dbsession.commit()
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

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit(
        self,
        dbsession,
        sample_commit_with_report_big,
        mock_storage,
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
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
                        "1/3",
                        None,
                        [[3, "1/2", None, None, None], [2, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        7,
                        "1/3",
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
                        "1/3",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        13,
                        "1/3",
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "1/3",
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
                        None,
                        None,
                    ],
                    "file_01.py": [
                        1,
                        [0, 10, 3, 0, 7, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_02.py": [
                        2,
                        [0, 11, 5, 0, 6, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_03.py": [
                        3,
                        [0, 15, 4, 2, 9, "26.66667", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_04.py": [
                        4,
                        [0, 10, 3, 1, 6, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_05.py": [
                        5,
                        [0, 13, 3, 2, 8, "23.07692", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_06.py": [
                        6,
                        [0, 7, 5, 0, 2, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_07.py": [
                        7,
                        [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_08.py": [
                        8,
                        [0, 11, 2, 4, 5, "18.18182", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_09.py": [
                        9,
                        [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_10.py": [
                        10,
                        [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_11.py": [
                        11,
                        [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_12.py": [
                        12,
                        [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_13.py": [
                        13,
                        [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_14.py": [
                        14,
                        [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        None,
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

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_with_labels(
        self, dbsession, sample_commit_with_report_big_with_labels
    ):
        parent_commit = sample_commit_with_report_big_with_labels
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert report.labels_index == {
            0: "Th2dMtk4M_codecov",
            1: "core/tests/test_menu_interface.py::TestMenuInterface::test_init",
            2: "core/tests/test_main.py::TestMainMenu::test_init_values",
            3: "core/tests/test_main.py::TestMainMenu::test_invalid_menu_choice",
            4: "core/tests/test_menu_interface.py::TestMenuInterface::test_menu_options",
            5: "core/tests/test_menu_interface.py::TestMenuInterface::test_set_loop",
            6: "core/tests/test_main.py::TestMainMenu::test_menu_choice_emotions",
            7: "core/tests/test_menu_interface.py::TestMenuInterface::test_name",
            8: "core/tests/test_menu_interface.py::TestMenuInterface::test_parent",
            9: "core/tests/test_main.py::TestMainMenu::test_menu_choice_fruits",
            10: "core/tests/test_main.py::TestMainMenu::test_menu_options",
        }
        assert sorted(report.files) == sorted(
            [
                "file_00.py",
                "file_01.py",
            ]
        )
        assert report.totals == ReportTotals(
            files=2,
            lines=36,
            hits=32,
            misses=4,
            partials=0,
            coverage="88.88889",
            branches=0,
            methods=0,
            messages=0,
            sessions=1,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        readable_report = self.convert_report_to_better_readable(report)
        expected_results = {
            "archive": {
                "file_00.py": [
                    (
                        1,
                        0,
                        None,
                        [[0, 0, None, None, None]],
                        None,
                        None,
                        [(0, 0, None, [])],
                    ),
                    (
                        3,
                        0,
                        None,
                        [[0, 0, None, None, None]],
                        None,
                        None,
                        [(0, 0, None, [])],
                    ),
                    (
                        4,
                        0,
                        None,
                        [[0, 0, None, None, None]],
                        None,
                        None,
                        [(0, 0, None, [])],
                    ),
                    (
                        5,
                        0,
                        None,
                        [[0, 0, None, None, None]],
                        None,
                        None,
                        [(0, 0, None, [])],
                    ),
                ],
                "file_01.py": [
                    (
                        1,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        2,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        5,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        6,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        7,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        8,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        9,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        12,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        13,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        14,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        16,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        17,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])],
                    ),
                    (
                        18,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])],
                    ),
                    (
                        19,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])],
                    ),
                    (
                        21,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        22,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        23,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [1, 3, 5, 6, 9])],
                    ),
                    (
                        25,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        26,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        27,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [1, 2, 8])],
                    ),
                    (
                        29,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        30,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        31,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [1, 2, 7])],
                    ),
                    (
                        33,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        34,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [3, 5, 6, 9])],
                    ),
                    (
                        36,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        37,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        38,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [3, 4, 6, 9, 10])],
                    ),
                    (
                        39,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [4])],
                    ),
                    (
                        41,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [3, 4, 6, 9, 10])],
                    ),
                    (
                        43,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, [0])],
                    ),
                    (
                        44,
                        0,
                        None,
                        [[0, 0, None, None, None]],
                        None,
                        None,
                        [(0, 0, None, [])],
                    ),
                ],
            },
            "report": {
                "files": {
                    "file_00.py": [
                        0,
                        [0, 4, 0, 4, 0, "0", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_01.py": [
                        1,
                        [0, 32, 32, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                },
                "sessions": {
                    "0": {
                        "N": "Carriedforward",
                        "a": None,
                        "c": None,
                        "d": None,
                        "e": None,
                        "f": ["enterprise"],
                        "j": None,
                        "n": None,
                        "p": None,
                        "se": {"carriedforward_from": parent_commit.commitid},
                        "st": "carriedforward",
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
                "c": "88.88889",
                "d": 0,
                "diff": None,
                "f": 2,
                "h": 32,
                "m": 4,
                "n": 36,
                "p": 0,
                "s": 1,
            },
        }
        assert expected_results["report"]["files"] == readable_report["report"]["files"]
        assert expected_results["report"] == readable_report["report"]
        assert expected_results == readable_report

    def test_create_new_report_for_commit_is_called_as_generate(
        self, dbsession, mocker
    ):
        commit = CommitFactory.create(_report_json=None)
        dbsession.add(commit)
        dbsession.flush()
        mocked_create_new_report_for_commit = mocker.patch.object(
            ReportService, "create_new_report_for_commit", return_value=Future()
        )
        mocked_create_new_report_for_commit.return_value.set_result("report")
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        report_service = ReportService(UserYaml(yaml_dict))
        report = report_service.build_report_from_commit(commit)
        assert report == mocked_create_new_report_for_commit.return_value

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_build_report_from_commit_carriedforward_add_sessions(
        self, dbsession, sample_commit_with_report_big, mocker
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}

        def fake_possibly_shift(report, base, head):
            return report

        mock_possibly_shift = mocker.patch.object(
            ReportService,
            "_possibly_shift_carryforward_report",
            side_effect=fake_possibly_shift,
        )
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert len(report.files) == 15
        mock_possibly_shift.assert_called()
        to_merge_session = Session(flags=["enterprise"])
        report.add_session(to_merge_session)
        assert sorted(report.sessions.keys()) == [2, 3, 4]
        assert _adjust_sessions(
            report, Report(), to_merge_session, UserYaml(yaml_dict)
        ) == SessionAdjustmentResult(
            fully_deleted_sessions=[2, 3], partially_deleted_sessions=[]
        )
        assert sorted(report.sessions.keys()) == [4]
        readable_report = self.convert_report_to_better_readable(report)
        expected_results = {
            "archive": {},
            "report": {
                "files": {},
                "sessions": {
                    "4": {
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
                "c": None,
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
        assert (
            readable_report["report"]["sessions"]
            == expected_results["report"]["sessions"]
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
        assert sorted(report.sessions.keys()) == [0, 1, 2, 3]
        first_to_merge_session = Session(flags=["enterprise"])
        report.add_session(first_to_merge_session)
        assert sorted(report.sessions.keys()) == [0, 1, 2, 3, 4]
        assert _adjust_sessions(
            report, Report(), first_to_merge_session, UserYaml(yaml_dict)
        ) == SessionAdjustmentResult(
            fully_deleted_sessions=[2, 3], partially_deleted_sessions=[]
        )
        assert sorted(report.sessions.keys()) == [0, 1, 4]
        readable_report = self.convert_report_to_better_readable(report)
        expected_sessions_dict = {
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
            "4": {
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
        assert readable_report["report"]["sessions"]["0"] == expected_sessions_dict["0"]
        assert readable_report["report"]["sessions"]["1"] == expected_sessions_dict["1"]
        assert readable_report["report"]["sessions"]["4"] == expected_sessions_dict["4"]
        assert readable_report["report"]["sessions"] == expected_sessions_dict
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
        second_to_merge_session = Session(flags=["unit"])
        report.add_session(second_to_merge_session)
        assert sorted(report.sessions.keys()) == [0, 1, 3, 4]
        assert _adjust_sessions(
            report, Report(), second_to_merge_session, UserYaml(yaml_dict)
        ) == SessionAdjustmentResult(
            fully_deleted_sessions=[], partially_deleted_sessions=[]
        )
        assert sorted(report.sessions.keys()) == [0, 1, 3, 4]
        new_readable_report = self.convert_report_to_better_readable(report)
        assert len(new_readable_report["report"]["sessions"]) == 4
        assert (
            new_readable_report["report"]["sessions"]["0"]
            == expected_sessions_dict["0"]
        )
        assert (
            new_readable_report["report"]["sessions"]["1"]
            == expected_sessions_dict["1"]
        )
        assert (
            new_readable_report["report"]["sessions"]["4"]
            == expected_sessions_dict["4"]
        )
        assert new_readable_report["report"]["sessions"]["3"] == newly_added_session

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_with_path_filters(
        self, dbsession, sample_commit_with_report_big, mocker
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
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

        def fake_possibly_shift(report, base, head):
            return report

        mock_possibly_shift = mocker.patch.object(
            ReportService,
            "_possibly_shift_carryforward_report",
            side_effect=fake_possibly_shift,
        )
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == sorted(
            ["file_10.py", "file_11.py", "file_12.py", "file_13.py", "file_14.py"]
        )
        mock_possibly_shift.assert_called()
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
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
                        "1/3",
                        None,
                        [[2, "1/2", None, None, None], [3, "1/3", None, None, None]],
                        None,
                        None,
                    ),
                    (
                        22,
                        "1/3",
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
                        None,
                        None,
                    ],
                    "file_11.py": [
                        11,
                        [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_12.py": [
                        12,
                        [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_13.py": [
                        13,
                        [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "file_14.py": [
                        14,
                        [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                        None,
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
        self, dbsession, sample_commit_with_report_big, mocker
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {
            "flags": {
                "enterprise": {"paths": ["file_1.*"]},
                "special_flag": {"paths": ["file_0.*"]},
            }
        }
        mock_possibly_shift = mocker.patch.object(
            ReportService, "_possibly_shift_carryforward_report"
        )
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == []
        mock_possibly_shift.assert_not_called()
        assert report.totals == ReportTotals(
            files=0,
            lines=0,
            hits=0,
            misses=0,
            partials=0,
            coverage=None,
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
            "report": {"files": {}, "sessions": {}},
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": None,
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

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_no_parent(
        self, dbsession, sample_commit_with_report_big, mocker
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=None,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        mock_possibly_shift = mocker.patch.object(
            ReportService, "_possibly_shift_carryforward_report"
        )
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        assert sorted(report.files) == []
        mock_possibly_shift.assert_not_called()
        assert report.totals == ReportTotals(
            files=0,
            lines=0,
            hits=0,
            misses=0,
            partials=0,
            coverage=None,
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
            "report": {"files": {}, "sessions": {}},
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": None,
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

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_parent_not_ready(
        self, dbsession, sample_commit_with_report_big, mocker
    ):
        grandparent_commit = sample_commit_with_report_big
        parent_commit = CommitFactory.create(
            repository=grandparent_commit.repository,
            parent_commit_id=grandparent_commit.commitid,
            _report_json=None,
            state="pending",
        )
        commit = CommitFactory.create(
            repository=grandparent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        mock_possibly_shift = mocker.patch.object(
            ReportService, "_possibly_shift_carryforward_report"
        )
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        mock_possibly_shift.assert_called()
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
                    None,
                    None,
                ],
                "file_01.py": [
                    1,
                    [0, 10, 3, 0, 7, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_02.py": [
                    2,
                    [0, 11, 5, 0, 6, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_03.py": [
                    3,
                    [0, 15, 4, 2, 9, "26.66667", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_04.py": [
                    4,
                    [0, 10, 3, 1, 6, "30.00000", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_05.py": [
                    5,
                    [0, 13, 3, 2, 8, "23.07692", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_06.py": [
                    6,
                    [0, 7, 5, 0, 2, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_07.py": [
                    7,
                    [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_08.py": [
                    8,
                    [0, 11, 2, 4, 5, "18.18182", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_09.py": [
                    9,
                    [0, 11, 5, 1, 5, "45.45455", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_10.py": [
                    10,
                    [0, 8, 3, 0, 5, "37.50000", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_11.py": [
                    11,
                    [0, 22, 8, 5, 9, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_12.py": [
                    12,
                    [0, 12, 4, 3, 5, "33.33333", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_13.py": [
                    13,
                    [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
                "file_14.py": [
                    14,
                    [0, 22, 8, 2, 12, "36.36364", 0, 0, 0, 0, 0, 0, 0],
                    None,
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

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_parent_not_ready_but_skipped(
        self, dbsession, sample_commit_with_report_big, mocker
    ):
        parent_commit = sample_commit_with_report_big
        parent_commit.state = "skipped"
        dbsession.flush()
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
        )
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        mock_possibly_shift = mocker.patch.object(
            ReportService, "_possibly_shift_carryforward_report"
        )
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        mock_possibly_shift.assert_called()
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
            }
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

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_too_many_ancestors_not_ready(
        self, dbsession, sample_commit_with_report_big, mocker
    ):
        grandparent_commit = sample_commit_with_report_big
        current_commit = grandparent_commit
        for i in range(10):
            current_commit = CommitFactory.create(
                repository=grandparent_commit.repository,
                parent_commit_id=current_commit.commitid,
                _report_json=None,
                state="pending",
            )
            dbsession.add(current_commit)
        commit = CommitFactory.create(
            repository=grandparent_commit.repository,
            parent_commit_id=current_commit.commitid,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        mock_possibly_shift = mocker.patch.object(
            ReportService, "_possibly_shift_carryforward_report"
        )
        report = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert report is not None
        mock_possibly_shift.assert_not_called()
        assert sorted(report.files) == []
        readable_report = self.convert_report_to_better_readable(report)
        expected_results_report = {"files": {}, "sessions": {}}
        assert expected_results_report == readable_report["report"]

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_parent_had_no_parent_and_pending(self, dbsession):
        current_commit = CommitFactory.create(parent_commit_id=None, state="pending")
        dbsession.add(current_commit)
        for i in range(5):
            current_commit = CommitFactory.create(
                repository=current_commit.repository,
                parent_commit_id=current_commit.commitid,
                _report_json=None,
                state="pending",
            )
            dbsession.add(current_commit)
        commit = CommitFactory.create(
            repository=current_commit.repository,
            parent_commit_id=current_commit.commitid,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
        with pytest.raises(NotReadyToBuildReportYetError):
            ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_potential_cf_but_not_real_cf(
        self, dbsession, sample_commit_with_report_big
    ):
        parent_commit = sample_commit_with_report_big
        dbsession.flush()
        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
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

    @pytest.mark.django_db(databases={"default", "timeseries"})
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

    def test_save_full_report(
        self, dbsession, mock_storage, sample_report, mock_configuration
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "only_codecov": False,
                        "report_details_files_array": True,
                    },
                }
            }
        )
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_details = ReportDetails(report_id=current_report_row.id_)
        dbsession.add(report_details)
        dbsession.flush()
        sample_report.sessions[0].archive = "path/to/upload/location"
        sample_report.sessions[
            0
        ].name = "this name contains more than 100 chars 1111111111111111111111111111111111111111111111111111111111111this is more than 100"
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
        dbsession.refresh(second_upload)
        dbsession.refresh(first_upload)
        assert first_upload.build_code == "aycaramba"
        assert first_upload.build_url is None
        assert first_upload.env is None
        assert first_upload.job_code is None
        assert (
            first_upload.name
            == "this name contains more than 100 chars 1111111111111111111111111111111111111111111111111111111111111"
        )
        assert first_upload.provider == "circleci"
        assert first_upload.report_id == current_report_row.id_
        assert first_upload.state == "complete"
        assert first_upload.storage_path == "path/to/upload/location"
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
        assert second_upload.storage_path == ""
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
                "diff_totals": None,
            },
        ]

    def test_save_report_empty_report(self, dbsession, mock_storage):
        report = Report()
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
        res = report_service.save_report(commit, report)
        storage_hash = report_service.get_archive_service(
            commit.repository
        ).storage_hash
        assert res == {
            "url": f"v4/repos/{storage_hash}/commits/{commit.commitid}/chunks.txt"
        }
        assert commit.totals == {
            "f": 0,
            "n": 0,
            "h": 0,
            "m": 0,
            "p": 0,
            "c": 0,
            "b": 0,
            "d": 0,
            "M": 0,
            "s": 0,
            "C": 0,
            "N": 0,
            "diff": None,
        }
        assert commit.report_json == {"files": {}, "sessions": {}}
        assert res["url"] in mock_storage.storage["archive"]
        assert (
            mock_storage.storage["archive"][res["url"]].decode()
            == "{}\n<<<<< end_of_header >>>>>\n"
        )

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
                "diff_totals": None,
            },
        ]
        expected = {
            "files": {
                "file_1.go": [
                    0,
                    [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0],
                    None,
                    None,
                ],
                "file_2.py": [
                    1,
                    [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                    None,
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
        expected_content = "\n".join(
            [
                "{}",
                "<<<<< end_of_header >>>>>",
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

    def test_save_report_file_needing_repack(
        self, dbsession, mock_storage, sample_report
    ):
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
        f = ReportFile("hahafile.txt")
        f.append(1, ReportLine.create(1))
        sample_report.append(f)
        f2 = ReportFile("poultry.c")
        f2.append(12, ReportLine.create(1))
        sample_report.append(f2)
        f3 = ReportFile("pulse.py")
        f3.append(2, ReportLine.create(1))
        sample_report.append(f3)
        del sample_report["file_2.py"]
        del sample_report["hahafile.txt"]
        del sample_report["pulse.py"]
        assert len(sample_report._chunks) > 2 * len(sample_report._files)
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
                "diff_totals": None,
            },
            {
                "filename": "poultry.c",
                "file_index": 1,
                "file_totals": ReportTotals(
                    files=0,
                    lines=1,
                    hits=1,
                    misses=0,
                    partials=0,
                    coverage="100",
                    branches=0,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=0,
                    complexity_total=0,
                    diff=0,
                ),
                "diff_totals": None,
            },
        ]
        expected = {
            "files": {
                "file_1.go": [
                    0,
                    [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0],
                    None,
                    None,
                ],
                "poultry.c": [
                    1,
                    [0, 1, 1, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    None,
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
        assert commit.report_json["files"] == expected["files"]
        assert commit.report_json == expected
        assert res["url"] in mock_storage.storage["archive"]
        expected_content = "\n".join(
            [
                "{}",
                "<<<<< end_of_header >>>>>",
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
                "[1]",
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

    @pytest.mark.django_db(databases={"default"})
    def test_initialize_and_save_report_carryforward_needed(
        self, dbsession, sample_commit_with_report_big, mocker, mock_storage
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            _report_json=None,
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
        assert first_upload.storage_path == ""
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
        assert second_upload.storage_path == ""
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

    @pytest.mark.django_db(databases={"default"})
    def test_initialize_and_save_report_report_but_no_details_carryforward_needed(
        self, dbsession, sample_commit_with_report_big, mock_storage
    ):
        parent_commit = sample_commit_with_report_big
        commit = CommitFactory.create(
            _report_json=None,
            parent_commit_id=parent_commit.commitid,
            repository=parent_commit.repository,
        )
        dbsession.add(commit)
        dbsession.flush()
        report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(report_row)
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
        assert first_upload.storage_path == ""
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
        assert second_upload.storage_path == ""
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
        self, dbsession, sample_commit_with_report_big, mock_storage, mocker
    ):
        commit = sample_commit_with_report_big
        report_service = ReportService({})
        mocker.patch.object(
            ReportDetails, "_should_write_to_storage", return_value=True
        )
        r = report_service.initialize_and_save_report(commit)
        assert r is not None
        assert r.details is not None
        assert len(r.uploads) == 4
        first_upload = dbsession.query(Upload).filter_by(order_number=0).first()
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
                "diff_totals": None,
            },
            {
                "filename": "file_01.py",
                "file_index": 1,
                "file_totals": [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_10.py",
                "file_index": 10,
                "file_totals": [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_11.py",
                "file_index": 11,
                "file_totals": [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_12.py",
                "file_index": 12,
                "file_totals": [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_13.py",
                "file_index": 13,
                "file_totals": [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_14.py",
                "file_index": 14,
                "file_totals": [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_02.py",
                "file_index": 2,
                "file_totals": [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_03.py",
                "file_index": 3,
                "file_totals": [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_04.py",
                "file_index": 4,
                "file_totals": [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_05.py",
                "file_index": 5,
                "file_totals": [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_06.py",
                "file_index": 6,
                "file_totals": [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_07.py",
                "file_index": 7,
                "file_totals": [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_08.py",
                "file_index": 8,
                "file_totals": [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_09.py",
                "file_index": 9,
                "file_totals": [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
        ]
        storage_keys = mock_storage.storage["archive"].keys()
        assert any(map(lambda key: key.endswith("chunks.txt"), storage_keys))

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

    @pytest.mark.django_db
    def test_create_report_upload(self, dbsession):
        arguments = {
            "branch": "master",
            "build": "646048900",
            "build_url": "http://github.com/greenlantern/reponame/actions/runs/646048900",
            "cmd_args": "n,F,Q,C",
            "commit": "1280bf4b8d596f41b101ac425758226c021876da",
            "job": "thisjob",
            "flags": "unittest",
            "name": "this name contains more than 100 chars 1111111111111111111111111111111111111111111111111111111111111this is more than 100",
            "owner": "greenlantern",
            "package": "github-action-20210309-2b87ace",
            "pr": "33",
            "repo": "reponame",
            "reportid": "6e2b6449-4e60-43f8-80ae-2c03a5c03d92",
            "service": "github-actions",
            "slug": "greenlantern/reponame",
            "upload_pk": "42593902",
            "url": "v4/raw/2021-03-12/C00AE6C87E34AF41A6D38D154C609782/1280bf4b8d596f41b101ac425758226c021876da/6e2b6449-4e60-43f8-80ae-2c03a5c03d92.txt",
            "using_global_token": "false",
            "version": "v4",
        }
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        current_report_row = CommitReport(commit_id=commit.id_)
        dbsession.add(current_report_row)
        dbsession.flush()
        report_service = ReportService({})
        res = report_service.create_report_upload(arguments, current_report_row)
        dbsession.flush()
        assert res.build_code == "646048900"
        assert (
            res.build_url
            == "http://github.com/greenlantern/reponame/actions/runs/646048900"
        )
        assert res.env is None
        assert res.job_code == "thisjob"
        assert (
            res.name
            == "this name contains more than 100 chars 1111111111111111111111111111111111111111111111111111111111111"
        )
        assert res.provider == "github-actions"
        assert res.report_id == current_report_row.id_
        assert res.state == "started"
        assert (
            res.storage_path
            == "v4/raw/2021-03-12/C00AE6C87E34AF41A6D38D154C609782/1280bf4b8d596f41b101ac425758226c021876da/6e2b6449-4e60-43f8-80ae-2c03a5c03d92.txt"
        )
        assert res.order_number is None
        assert res.totals is None
        assert res.upload_extras == {}
        assert res.upload_type == "uploaded"
        assert len(res.flags) == 1
        first_flag = res.flags[0]
        assert first_flag.flag_name == "unittest"
        assert first_flag.repository_id == commit.repoid

    def test_update_upload_with_processing_result_error(self, mocker, dbsession):
        upload_obj = UploadFactory.create(state="started", storage_path="url")
        dbsession.add(upload_obj)
        dbsession.flush()
        assert len(upload_obj.errors) == 0
        processing_result = ProcessingResult(
            session=mocker.MagicMock(),
            error=ProcessingError(code="abclkj", params={"banana": "value"}),
        )
        assert (
            ReportService({}).update_upload_with_processing_result(
                upload_obj, processing_result
            )
            is None
        )
        dbsession.refresh(upload_obj)
        assert upload_obj.state == "error"
        assert upload_obj.state_id == UploadState.ERROR.db_id
        assert len(upload_obj.errors) == 1
        assert upload_obj.errors[0].error_code == "abclkj"
        assert upload_obj.errors[0].error_params == {"banana": "value"}
        assert upload_obj.errors[0].report_upload == upload_obj

    def test_update_upload_with_processing_result_success(self, mocker, dbsession):
        upload_obj = UploadFactory.create(state="started", storage_path="url")
        dbsession.add(upload_obj)
        dbsession.flush()
        assert len(upload_obj.errors) == 0
        processing_result = ProcessingResult(
            session=Session(),
            error=None,
        )
        assert (
            ReportService({}).update_upload_with_processing_result(
                upload_obj, processing_result
            )
            is None
        )
        dbsession.refresh(upload_obj)
        assert upload_obj.state == "processed"
        assert upload_obj.state_id == UploadState.PROCESSED.db_id
        assert len(upload_obj.errors) == 0

    def test_shift_carryforward_report(
        self, dbsession, sample_report, mocker, mock_repo_provider
    ):
        parent_commit = CommitFactory()
        commit = CommitFactory(parent_commit_id=parent_commit.commitid)
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        fake_diff = {
            "diff": {
                "files": {
                    "file_1.go": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": [3, 3, 3, 4],
                                "lines": [
                                    " some go code in line 3",
                                    "-this line was removed",
                                    "+this line was added",
                                    "+this line was also added",
                                    " ",
                                ],
                            },
                            {
                                "header": [9, 1, 10, 5],
                                "lines": [
                                    " some go code in line 9",
                                    "+add",
                                    "+add",
                                    "+add",
                                    "+add",
                                ],
                            },
                        ],
                    }
                }
            }
        }

        def fake_get_compare(base, head):
            assert base == parent_commit.commitid
            assert head == commit.commitid
            return fake_diff

        mock_repo_provider.get_compare = mock.AsyncMock(side_effect=fake_get_compare)
        result = ReportService({})._possibly_shift_carryforward_report(
            sample_report, parent_commit, commit
        )
        readable_report = self.convert_report_to_better_readable(result)
        assert readable_report["archive"] == {
            "file_1.go": [
                (1, 1, None, [[0, 1, None, None, None]], None, (10, 2)),
                (2, 0, None, [[0, 1, None, None, None]], None, None),
                (3, 1, None, [[0, 1, None, None, None]], None, None),
                (
                    6,
                    1,
                    None,
                    [[0, 1, None, None, None], [1, 1, None, None, None]],
                    None,
                    None,
                ),
                (7, 0, None, [[0, 1, None, None, None]], None, None),
                (
                    9,
                    1,
                    None,
                    [[0, 1, None, None, None], [1, 0, None, None, None]],
                    None,
                    None,
                ),
                (10, 1, None, [[0, 1, None, None, None]], None, None),
                (15, 0, None, [[0, 1, None, None, None]], None, None),
            ],
            "file_2.py": [
                (12, 1, None, [[0, 1, None, None, None]], None, None),
                (51, "1/2", "b", [[0, 1, None, None, None]], None, None),
            ],
        }

    @pytest.mark.django_db(databases={"default", "timeseries"})
    def test_create_new_report_for_commit_and_shift(
        self, dbsession, sample_report, mocker, mock_repo_provider, mock_storage
    ):
        parent_commit = CommitFactory()
        parent_commit_report = CommitReport(commit_id=parent_commit.id_)
        parent_report_details = ReportDetails(report_id=parent_commit_report.id_)
        dbsession.add(parent_commit)
        dbsession.add(parent_commit_report)
        dbsession.add(parent_report_details)
        dbsession.flush()

        commit = CommitFactory.create(
            repository=parent_commit.repository,
            parent_commit_id=parent_commit.commitid,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.flush()
        dbsession.add(CommitReport(commit_id=commit.id_))
        dbsession.flush()
        yaml_dict = {
            "flags": {
                "integration": {"carryforward": True},
                "unit": {"carryforward": True},
            }
        }

        fake_diff = {
            "diff": {
                "files": {
                    "file_1.go": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": [3, 3, 3, 4],
                                "lines": [
                                    " some go code in line 3",
                                    "-this line was removed",
                                    "+this line was added",
                                    "+this line was also added",
                                    " ",
                                ],
                            },
                            {
                                "header": [9, 1, 10, 5],
                                "lines": [
                                    " some go code in line 9",
                                    "+add",
                                    "+add",
                                    "+add",
                                    "+add",
                                ],
                            },
                        ],
                    }
                }
            }
        }

        def fake_get_compare(base, head):
            assert base == parent_commit.commitid
            assert head == commit.commitid
            return fake_diff

        mock_repo_provider.get_compare = mock.AsyncMock(side_effect=fake_get_compare)

        mock_get_report = mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=sample_report
        )

        result = ReportService(UserYaml(yaml_dict)).create_new_report_for_commit(commit)
        assert mock_get_report.call_count == 1
        readable_report = self.convert_report_to_better_readable(result)
        assert readable_report["archive"] == {
            "file_1.go": [
                (1, 1, None, [[0, 1, None, None, None]], None, (10, 2)),
                (2, 0, None, [[0, 1, None, None, None]], None, None),
                (3, 1, None, [[0, 1, None, None, None]], None, None),
                (
                    6,
                    1,
                    None,
                    [[0, 1, None, None, None], [1, 1, None, None, None]],
                    None,
                    None,
                ),
                (7, 0, None, [[0, 1, None, None, None]], None, None),
                (
                    9,
                    1,
                    None,
                    [[0, 1, None, None, None], [1, 0, None, None, None]],
                    None,
                    None,
                ),
                (10, 1, None, [[0, 1, None, None, None]], None, None),
                (15, 0, None, [[0, 1, None, None, None]], None, None),
            ],
            "file_2.py": [
                (12, 1, None, [[0, 1, None, None, None]], None, None),
                (51, "1/2", "b", [[0, 1, None, None, None]], None, None),
            ],
        }

    def test_possibly_shift_carryforward_report_cant_get_diff(
        self, dbsession, sample_report, mocker
    ):
        parent_commit = CommitFactory()
        commit = CommitFactory(parent_commit_id=parent_commit.commitid)
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        mock_log_error = mocker.patch.object(report_log, "error")

        def raise_error(*args, **kwargs):
            raise TorngitRateLimitError(response_data="", message="error", reset=None)

        fake_provider = mocker.Mock()
        fake_provider.get_compare = raise_error
        mock_provider_service = mocker.patch(
            "services.report.get_repo_provider_service", return_value=fake_provider
        )
        result = ReportService({})._possibly_shift_carryforward_report(
            sample_report, parent_commit, commit
        )
        assert result == sample_report
        mock_provider_service.assert_called()
        mock_log_error.assert_called_with(
            "Failed to shift carryforward report lines.",
            extra=dict(
                reason="Can't get diff",
                commit=commit.commitid,
                error=str(
                    TorngitRateLimitError(response_data="", message="error", reset=None)
                ),
                error_type=type(
                    TorngitRateLimitError(response_data="", message="error", reset=None)
                ),
            ),
        )

    def test_possibly_shift_carryforward_report_bot_error(
        self, dbsession, sample_report, mocker
    ):
        parent_commit = CommitFactory()
        commit = CommitFactory(parent_commit_id=parent_commit.commitid)
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        mock_log_error = mocker.patch.object(report_log, "error")

        def raise_error(*args, **kwargs):
            raise RepositoryWithoutValidBotError()

        mock_provider_service = mocker.patch(
            "services.report.get_repo_provider_service", side_effect=raise_error
        )
        result = ReportService({})._possibly_shift_carryforward_report(
            sample_report, parent_commit, commit
        )
        assert result == sample_report
        mock_provider_service.assert_called()
        mock_log_error.assert_called_with(
            "Failed to shift carryforward report lines",
            extra=dict(
                reason="Can't get provider_service",
                commit=commit.commitid,
                error=str(RepositoryWithoutValidBotError()),
            ),
        )

    def test_possibly_shift_carryforward_report_random_processing_error(
        self, dbsession, mocker, mock_repo_provider
    ):
        parent_commit = CommitFactory()
        commit = CommitFactory(parent_commit_id=parent_commit.commitid)
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()
        mock_log_error = mocker.patch.object(report_log, "error")

        def raise_error(*args, **kwargs):
            raise Exception("Very random and hard to get exception")

        mock_repo_provider.get_compare = mock.AsyncMock(
            side_effect=lambda *args, **kwargs: dict(diff={})
        )
        mock_report = mocker.Mock()
        mock_report.shift_lines_by_diff = raise_error
        result = ReportService({})._possibly_shift_carryforward_report(
            mock_report, parent_commit, commit
        )
        assert result == mock_report
        mock_log_error.assert_called_with(
            "Failed to shift carryforward report lines.",
            exc_info=True,
            extra=dict(
                reason="Unknown",
                commit=commit.commitid,
            ),
        )

    def test_possibly_shift_carryforward_report_softtimelimit_reraised(
        self, dbsession, mocker, mock_repo_provider
    ):
        parent_commit = CommitFactory()
        commit = CommitFactory(parent_commit_id=parent_commit.commitid)
        dbsession.add(parent_commit)
        dbsession.add(commit)
        dbsession.flush()

        def raise_error(*args, **kwargs):
            raise SoftTimeLimitExceeded()

        mock_report = mocker.Mock()
        mock_report.shift_lines_by_diff = raise_error
        with pytest.raises(SoftTimeLimitExceeded):
            ReportService({})._possibly_shift_carryforward_report(
                mock_report, parent_commit, commit
            )
