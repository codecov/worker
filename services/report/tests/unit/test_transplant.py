import pytest
from shared.django_apps.core.tests.factories import (
    CommitFactory,
    CommitWithReportFactory,
    RepositoryFactory,
)
from shared.django_apps.reports.models import ReportLevelTotals

from services.archive import ArchiveService
from services.report.transplant import transplant_commit_report


@pytest.mark.django_db()
def test_transplanting_commit(mock_storage):
    repo = RepositoryFactory()
    commit_from = CommitWithReportFactory(repository=repo)

    archive_service = ArchiveService(repo)
    with open("tasks/tests/samples/sample_chunks_1.txt", "rb") as f:
        chunks = f.read()
    archive_service.write_chunks(commit_from.commitid, chunks)

    commit_to = CommitFactory(repository=repo)

    transplant_commit_report(
        repo_id=repo.repoid, from_sha=commit_from.commitid, to_sha=commit_to.commitid
    )
    commit_to.refresh_from_db()

    from_totals = commit_from.commitreport.reportleveltotals
    to_totals = commit_to.commitreport.reportleveltotals

    def totals_tuple(totals: ReportLevelTotals):
        return (
            totals.branches,
            totals.coverage,
            totals.hits,
            totals.lines,
            totals.methods,
            totals.misses,
            totals.partials,
            totals.files,
        )

    assert totals_tuple(from_totals) == totals_tuple(to_totals)

    report = commit_to.full_report
    file = report.get("tests/__init__.py")
    assert file.get(1).coverage == 1
