from pathlib import Path

from shared.bundle_analysis.storage import get_bucket_name

from database.enums import ReportType
from database.models.core import Commit, Repository
from database.models.reports import CommitReport
from database.tests.factories.core import CommitFactory, PullFactory
from services.archive import ArchiveService
from services.repository import EnrichedPull

SAMPLE_FOLDER_PATH = Path(__file__).resolve().parent / "tests" / "samples"


def get_commit_pair(dbsession) -> tuple[Commit, Commit]:
    base_commit = CommitFactory()
    head_commit = CommitFactory(repository=base_commit.repository)
    dbsession.add_all([base_commit, head_commit])
    dbsession.commit()
    return (head_commit, base_commit)


def get_report_pair(dbsession, commit_pair) -> tuple[CommitReport, CommitReport]:
    head_commit, base_commit = commit_pair
    base_commit_report = CommitReport(
        commit=base_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    head_commit_report = CommitReport(
        commit=head_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add_all([base_commit_report, head_commit_report])
    dbsession.commit()
    return (head_commit_report, base_commit_report)


def get_enriched_pull_setting_up_mocks(dbsession, mocker, commit_pair) -> EnrichedPull:
    head_commit, base_commit = commit_pair
    pull = PullFactory(
        repository=base_commit.repository,
        head=head_commit.commitid,
        base=base_commit.commitid,
        compared_to=base_commit.commitid,
    )
    dbsession.add(pull)
    dbsession.commit()
    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )
    mocker.patch(
        "services.bundle_analysis.new_notify.contexts.comment.fetch_and_update_pull_request_information_from_commit",
        return_value=enriched_pull,
    )
    fake_repo_service = mocker.MagicMock(name="fake_repo_service")
    mocker.patch(
        "services.bundle_analysis.new_notify.contexts.get_repo_provider_service",
        return_value=fake_repo_service,
    )

    return enriched_pull


def save_mock_bundle_analysis_report(
    repository: Repository,
    commit_report: CommitReport,
    mock_storage,
    sample_report_number,
) -> None:
    repo_key = ArchiveService.get_archive_hash(repository)
    sample_path = SAMPLE_FOLDER_PATH / f"sample_{sample_report_number}.sqlite"
    sample_contents = sample_path.read_bytes()
    mock_storage.write_file(
        get_bucket_name(),
        f"v1/repos/{repo_key}/{commit_report.external_id}/bundle_report.sqlite",
        sample_contents,
    )
