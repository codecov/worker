import pytest

from database.models.reports import CommitReport
from database.tests.factories import CommitFactory
from services.report import ReportService


def test_fetch_fail_raises(dbsession):
    service = ReportService({})
    commit = CommitFactory.create(
        message="",
        parent_commit_id=None,
        repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
        repository__owner__username="ThiagoCodecov",
        repository__yaml={"codecov": {"max_report_age": "764y ago"}},
    )
    report = CommitReport(commit_id=commit.id_)
    dbsession.add(commit)
    dbsession.add(report)
    dbsession.flush()
    with pytest.raises(Exception) as exp:
        service.fetch_report_upload(report, 100000)
    assert "Failed to find existing upload by ID (100000)" in str(exp)
