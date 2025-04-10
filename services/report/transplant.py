from shared.django_apps.core.models import Commit
from shared.django_apps.reports.models import CommitReport, ReportType

from services.archive import ArchiveService


def transplant_commit_report(repo_id: int, from_sha: str, to_sha: str):
    """
    This copies a `Report` from one commit to another commit.

    The `to_sha` commit has to exist already (being auto-created using a git provider sync).

    It does so by creating a copy of the underlying `report_json` and `chunks` storage files,
    as well as some related DB models.
    """

    from_commit = Commit.objects.select_related("repository").get(
        repository=repo_id, commitid=from_sha
    )
    to_commit = Commit.objects.get(repository=repo_id, commitid=to_sha)

    archive_service = ArchiveService(from_commit.repository)

    chunks = archive_service.read_chunks(from_commit.commitid)
    report_json = from_commit.report
    totals = from_commit.totals

    archive_service.write_chunks(to_commit.commitid, chunks)

    to_commit.report = report_json
    to_commit.totals = totals
    to_commit.state = "complete"
    to_commit.save()

    if old_commit_report := from_commit.commitreport:
        commit_report = CommitReport(
            commit=to_commit, report_type=ReportType.COVERAGE.value
        )
        commit_report.save()

        if totals := old_commit_report.reportleveltotals:
            # See <https://docs.djangoproject.com/en/5.1/topics/db/queries/#copying-model-instances>
            totals.pk = None
            totals.id = None
            totals._state.adding = True

            totals.report = commit_report
            totals.save()

    # TODO:
    # We might also have to create copies of all of `Upload` (aka `Reportsession`),
    # `UploadLevelTotals`, `UploadError` and `UploadFlagMembership`
