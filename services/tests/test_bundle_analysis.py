import pytest
from shared.bundle_analysis.comparison import BundleChange, BundleReport
from shared.yaml import UserYaml

from database.enums import ReportType
from database.models import CommitReport
from database.tests.factories import CommitFactory, PullFactory
from services.archive import ArchiveService
from services.bundle_analysis import Notifier, get_bucket_name
from services.repository import EnrichedPull

expected_message_increase = """## Bundle Report

Changes will increase total bundle size by 3.46KB :arrow_up:

| Bundle name | Size | Change |
| ----------- | ---- | ------ |
| test-bundle | 123.46KB | 3.46KB :arrow_up: |"""

expected_message_decrease = """## Bundle Report

Changes will decrease total bundle size by 3.46KB :arrow_down:

| Bundle name | Size | Change |
| ----------- | ---- | ------ |
| test-bundle | 123.46KB | 3.46KB :arrow_down: |"""


class MockBundleReport:
    def total_size(self):
        return 123456


def test_bytes_readable():
    notifier = Notifier(None, UserYaml.from_dict({}))
    assert notifier._bytes_readable(999) == "999 bytes"
    assert notifier._bytes_readable(1234) == "1.23KB"
    assert notifier._bytes_readable(123456) == "123.46KB"
    assert notifier._bytes_readable(1234567) == "1.23MB"
    assert notifier._bytes_readable(1234567890) == "1.23GB"


@pytest.mark.asyncio
async def test_bundle_analysis_notify(
    dbsession, mocker, mock_storage, mock_repo_provider
):
    base_commit = CommitFactory()
    dbsession.add(base_commit)
    base_commit_report = CommitReport(
        commit=base_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(base_commit_report)

    head_commit = CommitFactory(repository=base_commit.repository)
    dbsession.add(head_commit)
    head_commit_report = CommitReport(
        commit=head_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(head_commit_report)

    pull = PullFactory(
        repository=base_commit.repository,
        head=head_commit.commitid,
        base=base_commit.commitid,
        compared_to=base_commit.commitid,
    )
    dbsession.add(pull)
    dbsession.commit()

    notifier = Notifier(head_commit, UserYaml.from_dict({}))

    repo_key = ArchiveService.get_archive_hash(base_commit.repository)
    mock_storage.write_file(
        get_bucket_name(),
        f"v1/repos/{repo_key}/{base_commit_report.external_id}/bundle_report.sqlite",
        "test-content",
    )
    mock_storage.write_file(
        get_bucket_name(),
        f"v1/repos/{repo_key}/{head_commit_report.external_id}/bundle_report.sqlite",
        "test-content",
    )

    mocker.patch(
        "services.bundle_analysis.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.get_repo_provider_service",
        return_value=mock_repo_provider,
    )

    bundle_changes = mocker.patch(
        "shared.bundle_analysis.comparison.BundleAnalysisComparison.bundle_changes"
    )
    bundle_changes.return_value = [
        BundleChange("test-bundle", BundleChange.ChangeType.CHANGED, size_delta=3456),
    ]

    bundle_report = mocker.patch(
        "shared.bundle_analysis.report.BundleAnalysisReport.bundle_report"
    )
    bundle_report.return_value = MockBundleReport()

    fetch_pr = mocker.patch(
        "services.bundle_analysis.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )

    mock_repo_provider.post_comment.return_value = {"id": "test-comment-id"}

    success = await notifier.notify()
    assert success == True
    mock_repo_provider.post_comment.assert_called_once_with(
        pull.pullid, expected_message_increase
    )

    success = await notifier.notify()
    assert success == True
    mock_repo_provider.edit_comment.assert_called_once_with(
        pull.pullid, "test-comment-id", expected_message_increase
    )


@pytest.mark.asyncio
async def test_bundle_analysis_notify_size_decrease(
    dbsession, mocker, mock_storage, mock_repo_provider
):
    base_commit = CommitFactory()
    dbsession.add(base_commit)
    base_commit_report = CommitReport(
        commit=base_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(base_commit_report)

    head_commit = CommitFactory(repository=base_commit.repository)
    dbsession.add(head_commit)
    head_commit_report = CommitReport(
        commit=head_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(head_commit_report)

    pull = PullFactory(
        repository=base_commit.repository,
        head=head_commit.commitid,
        base=base_commit.commitid,
        compared_to=base_commit.commitid,
    )
    dbsession.add(pull)
    dbsession.commit()

    notifier = Notifier(head_commit, UserYaml.from_dict({}))

    repo_key = ArchiveService.get_archive_hash(base_commit.repository)
    mock_storage.write_file(
        get_bucket_name(),
        f"v1/repos/{repo_key}/{base_commit_report.external_id}/bundle_report.sqlite",
        "test-content",
    )
    mock_storage.write_file(
        get_bucket_name(),
        f"v1/repos/{repo_key}/{head_commit_report.external_id}/bundle_report.sqlite",
        "test-content",
    )

    mocker.patch(
        "services.bundle_analysis.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.get_repo_provider_service",
        return_value=mock_repo_provider,
    )

    bundle_changes = mocker.patch(
        "shared.bundle_analysis.comparison.BundleAnalysisComparison.bundle_changes"
    )
    bundle_changes.return_value = [
        BundleChange("test-bundle", BundleChange.ChangeType.CHANGED, size_delta=-3456),
    ]

    bundle_report = mocker.patch(
        "shared.bundle_analysis.report.BundleAnalysisReport.bundle_report"
    )
    bundle_report.return_value = MockBundleReport()

    fetch_pr = mocker.patch(
        "services.bundle_analysis.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )

    success = await notifier.notify()
    assert success == True
    mock_repo_provider.post_comment.assert_called_once_with(
        pull.pullid, expected_message_decrease
    )


@pytest.mark.asyncio
async def test_bundle_analysis_notify_missing_commit_report(
    dbsession, mocker, mock_storage, mock_repo_provider
):
    base_commit = CommitFactory()
    dbsession.add(base_commit)
    base_commit_report = CommitReport(
        commit=base_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(base_commit_report)

    head_commit = CommitFactory(repository=base_commit.repository)
    dbsession.add(head_commit)

    notifier = Notifier(head_commit, UserYaml.from_dict({}))

    success = await notifier.notify()
    assert success == False


@pytest.mark.asyncio
async def test_bundle_analysis_notify_missing_bundle_report(
    dbsession, mocker, mock_storage, mock_repo_provider
):
    base_commit = CommitFactory()
    dbsession.add(base_commit)
    base_commit_report = CommitReport(
        commit=base_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(base_commit_report)

    head_commit = CommitFactory(repository=base_commit.repository)
    dbsession.add(head_commit)
    head_commit_report = CommitReport(
        commit=head_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(head_commit_report)

    pull = PullFactory(
        repository=base_commit.repository,
        head=head_commit.commitid,
        base=base_commit.commitid,
        compared_to=base_commit.commitid,
    )
    dbsession.add(pull)
    dbsession.commit()

    notifier = Notifier(head_commit, UserYaml.from_dict({}))

    success = await notifier.notify()
    assert success == False


@pytest.mark.asyncio
async def test_bundle_analysis_notify_missing_pull(
    dbsession, mocker, mock_storage, mock_repo_provider
):
    base_commit = CommitFactory()
    dbsession.add(base_commit)
    base_commit_report = CommitReport(
        commit=base_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(base_commit_report)

    head_commit = CommitFactory(repository=base_commit.repository)
    dbsession.add(head_commit)
    head_commit_report = CommitReport(
        commit=head_commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(head_commit_report)

    pull = PullFactory(
        repository=base_commit.repository,
        head=head_commit.commitid,
        base=base_commit.commitid,
        compared_to=base_commit.commitid,
    )
    dbsession.add(pull)
    dbsession.commit()

    notifier = Notifier(head_commit, UserYaml.from_dict({}))

    repo_key = ArchiveService.get_archive_hash(base_commit.repository)
    mock_storage.write_file(
        get_bucket_name(),
        f"v1/repos/{repo_key}/{base_commit_report.external_id}/bundle_report.sqlite",
        "test-content",
    )
    mock_storage.write_file(
        get_bucket_name(),
        f"v1/repos/{repo_key}/{head_commit_report.external_id}/bundle_report.sqlite",
        "test-content",
    )

    mocker.patch(
        "services.bundle_analysis.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.get_repo_provider_service",
        return_value=mock_repo_provider,
    )

    bundle_changes = mocker.patch(
        "shared.bundle_analysis.comparison.BundleAnalysisComparison.bundle_changes"
    )
    bundle_changes.return_value = [
        BundleChange("test-bundle", BundleChange.ChangeType.CHANGED, size_delta=3456),
    ]

    bundle_report = mocker.patch(
        "shared.bundle_analysis.report.BundleAnalysisReport.bundle_report"
    )
    bundle_report.return_value = MockBundleReport()

    fetch_pr = mocker.patch(
        "services.bundle_analysis.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = None

    success = await notifier.notify()
    assert success == False
