from tests.base import BaseTestCase
from services.report import ReportService
from database.tests.factories import CommitFactory
from services.archive import ArchiveService
from covreports.reports.types import ReportTotals


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
