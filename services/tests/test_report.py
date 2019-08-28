from tests.base import BaseTestCase
from services.report import ReportService
from database.tests.factories import CommitFactory


class TestReportService(BaseTestCase):

    def test_build_report_from_commit_no_report_saved(self, mocker):
        commit = CommitFactory.create(
            report=None
        )
        res = ReportService().build_report_from_commit(commit)
        assert res is not None
        assert res.files == []
        assert tuple(res.totals) == (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
