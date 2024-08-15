import pytest
from shared.bundle_analysis.comparison import BundleChange
from shared.bundle_analysis.models import AssetType
from shared.bundle_analysis.storage import get_bucket_name
from shared.yaml import UserYaml

from database.enums import ReportType
from database.models import CommitReport, MeasurementName
from database.tests.factories import CommitFactory, PullFactory, UploadFactory
from database.tests.factories.timeseries import DatasetFactory, Measurement
from services.archive import ArchiveService
from services.bundle_analysis.notify import Notifier
from services.bundle_analysis.report import (
    BundleAnalysisReportService,
    ProcessingResult,
)
from services.repository import EnrichedPull
from services.urls import get_bundle_analysis_pull_url


class MockBundleReport:
    def total_size(self):
        return 123456


def test_bytes_readable():
    notifier = Notifier(None, UserYaml.from_dict({}))
    assert notifier._bytes_readable(999) == "999 bytes"
    assert notifier._bytes_readable(1234) == "1.23kB"
    assert notifier._bytes_readable(123456) == "123.46kB"
    assert notifier._bytes_readable(1234567) == "1.23MB"
    assert notifier._bytes_readable(1234567890) == "1.23GB"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config, should_notify",
    [
        pytest.param({}, True, id="default_config"),
        pytest.param(
            {"comment": {"require_bundle_changes": False}},
            True,
            id="no_required_changes",
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": True}}, True, id="required_changes"
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": "bundle_increase"}},
            True,
            id="required_increase",
        ),
        pytest.param(
            {
                "comment": {
                    "require_bundle_changes": "bundle_increase",
                    "bundle_change_threshold": 1000,
                }
            },
            True,
            id="required_increase_with_small_threshold",
        ),
        pytest.param(
            {
                "comment": {
                    "require_bundle_changes": "bundle_increase",
                    "bundle_change_threshold": 1000000,
                }
            },
            False,
            id="required_increase_with_big_threshold",
        ),
    ],
)
async def test_bundle_analysis_notify(
    config, should_notify, dbsession, mocker, mock_storage, mock_repo_provider
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

    notifier = Notifier(head_commit, UserYaml.from_dict(config))

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
        "services.bundle_analysis.comparison.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.notify.get_repo_provider_service",
        return_value=mock_repo_provider,
    )

    bundle_changes = mocker.patch(
        "shared.bundle_analysis.comparison.BundleAnalysisComparison.bundle_changes"
    )
    bundle_changes.return_value = [
        BundleChange("added-bundle", BundleChange.ChangeType.ADDED, size_delta=12345),
        BundleChange(
            "changed-bundle", BundleChange.ChangeType.CHANGED, size_delta=3456
        ),
        BundleChange(
            "removed-bundle", BundleChange.ChangeType.REMOVED, size_delta=-1234
        ),
    ]

    bundle_report = mocker.patch(
        "shared.bundle_analysis.report.BundleAnalysisReport.bundle_report"
    )
    bundle_report.return_value = MockBundleReport()

    fetch_pr = mocker.patch(
        "services.bundle_analysis.notify.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )
    url = get_bundle_analysis_pull_url(pull=pull)
    expected_message_increase = f"""## [Bundle]({url}) Report

Changes will increase total bundle size by 14.57kB :arrow_up:

| Bundle name | Size | Change |
| ----------- | ---- | ------ |
| added-bundle | 123.46kB | 12.35kB :arrow_up: |
| changed-bundle | 123.46kB | 3.46kB :arrow_up: |
| removed-bundle | (removed) | 1.23kB :arrow_down: |"""

    mock_repo_provider.post_comment.return_value = {"id": "test-comment-id"}

    success = await notifier.notify()
    assert success == True
    if should_notify:
        assert pull.bundle_analysis_commentid is not None
        mock_repo_provider.post_comment.assert_called_once_with(
            pull.pullid, expected_message_increase
        )
    else:
        assert pull.bundle_analysis_commentid is None
        mock_repo_provider.post_comment.assert_not_called()

    success = await notifier.notify()
    assert success == True
    if should_notify:
        assert pull.bundle_analysis_commentid is not None
        mock_repo_provider.edit_comment.assert_called_once_with(
            pull.pullid, "test-comment-id", expected_message_increase
        )
    else:
        assert pull.bundle_analysis_commentid is None
        mock_repo_provider.edit_comment.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config, should_notify",
    [
        pytest.param({}, True, id="default_config"),
        pytest.param(
            {"comment": {"require_bundle_changes": False}},
            True,
            id="no_required_changes",
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": True}}, True, id="required_changes"
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": "bundle_increase"}},
            False,
            id="required_increase",
        ),
        pytest.param(
            {
                "comment": {
                    "require_bundle_changes": True,
                    "bundle_change_threshold": 1000,
                }
            },
            True,
            id="required_increase_with_small_threshold",
        ),
        pytest.param(
            {
                "comment": {
                    "require_bundle_changes": True,
                    "bundle_change_threshold": 1000000,
                }
            },
            False,
            id="required_increase_with_big_threshold",
        ),
    ],
)
async def test_bundle_analysis_notify_size_decrease(
    config, should_notify, dbsession, mocker, mock_storage, mock_repo_provider
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

    notifier = Notifier(head_commit, UserYaml.from_dict(config))

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
        "services.bundle_analysis.comparison.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.notify.get_repo_provider_service",
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
        "services.bundle_analysis.notify.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )

    url = get_bundle_analysis_pull_url(pull=pull)
    expected_message_decrease = f"""## [Bundle]({url}) Report

Changes will decrease total bundle size by 3.46kB :arrow_down:

| Bundle name | Size | Change |
| ----------- | ---- | ------ |
| test-bundle | 123.46kB | 3.46kB :arrow_down: |"""

    success = await notifier.notify()
    assert success == True
    if should_notify:
        assert pull.bundle_analysis_commentid is not None
        mock_repo_provider.post_comment.assert_called_once_with(
            pull.pullid, expected_message_decrease
        )
    else:
        assert pull.bundle_analysis_commentid is None
        mock_repo_provider.post_comment.assert_not_called()


@pytest.mark.asyncio
async def test_bundle_analysis_notify_size_unchanged(
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
        "services.bundle_analysis.comparison.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.notify.get_repo_provider_service",
        return_value=mock_repo_provider,
    )

    bundle_changes = mocker.patch(
        "shared.bundle_analysis.comparison.BundleAnalysisComparison.bundle_changes"
    )
    bundle_changes.return_value = [
        BundleChange("test-bundle", BundleChange.ChangeType.CHANGED, size_delta=0),
    ]

    bundle_report = mocker.patch(
        "shared.bundle_analysis.report.BundleAnalysisReport.bundle_report"
    )
    bundle_report.return_value = MockBundleReport()

    fetch_pr = mocker.patch(
        "services.bundle_analysis.notify.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )
    url = get_bundle_analysis_pull_url(pull=pull)
    expected_message_unchanged = f"""## [Bundle]({url}) Report

Bundle size has no change :white_check_mark:"""

    success = await notifier.notify()
    assert success == True
    mock_repo_provider.post_comment.assert_called_once_with(
        pull.pullid, expected_message_unchanged
    )


@pytest.mark.asyncio
async def test_bundle_analysis_no_notification_size_unchanged(
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

    notifier = Notifier(
        head_commit, UserYaml.from_dict({"comment": {"require_bundle_changes": True}})
    )

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
        "services.bundle_analysis.comparison.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.notify.get_repo_provider_service",
        return_value=mock_repo_provider,
    )

    bundle_changes = mocker.patch(
        "shared.bundle_analysis.comparison.BundleAnalysisComparison.bundle_changes"
    )
    bundle_changes.return_value = [
        BundleChange("test-bundle", BundleChange.ChangeType.CHANGED, size_delta=0),
    ]

    bundle_report = mocker.patch(
        "shared.bundle_analysis.report.BundleAnalysisReport.bundle_report"
    )
    bundle_report.return_value = MockBundleReport()

    fetch_pr = mocker.patch(
        "services.bundle_analysis.notify.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )

    success = await notifier.notify()
    assert success == True
    mock_repo_provider.post_comment.assert_not_called()
    mock_repo_provider.edit_comment.assert_not_called()


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
        "services.bundle_analysis.comparison.get_appropriate_storage_service",
        return_value=mock_storage,
    )
    mocker.patch("shared.bundle_analysis.report.BundleAnalysisReport._setup")
    mocker.patch(
        "services.bundle_analysis.notify.get_repo_provider_service",
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
        "services.bundle_analysis.notify.fetch_and_update_pull_request_information_from_commit"
    )
    fetch_pr.return_value = None

    success = await notifier.notify()
    assert success == False


@pytest.mark.asyncio
async def test_bundle_analysis_save_measurements_report_size(
    dbsession, mocker, mock_storage
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    commit = CommitFactory()
    dbsession.add(commit)
    dbsession.commit()

    commit_report = CommitReport(
        commit=commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(commit_report)
    dbsession.commit()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.commit()

    dataset = DatasetFactory.create(
        name=MeasurementName.bundle_analysis_report_size.value,
        repository_id=commit.repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.commit()

    class MockBundleReport:
        def __init__(self, bundle_name, size):
            self.bundle_name = bundle_name
            self.size = size

        @property
        def name(self):
            return self.bundle_name

        def total_size(self):
            return self.size

    class MockBundleAnalysisReport:
        def bundle_reports(self):
            return [
                MockBundleReport("BundleA", 1111),
                MockBundleReport("BundleB", 2222),
            ]

    mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
        return_value=MockBundleAnalysisReport(),
    )

    report_service = BundleAnalysisReportService(UserYaml.from_dict({}))
    result: ProcessingResult = report_service.save_measurements(commit, upload)

    assert result.error is None

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_report_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="BundleA",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 1111

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_report_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="BundleB",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 2222


@pytest.mark.asyncio
async def test_bundle_analysis_save_measurements_asset_size(
    dbsession, mocker, mock_storage
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    commit = CommitFactory()
    dbsession.add(commit)
    dbsession.commit()

    commit_report = CommitReport(
        commit=commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(commit_report)
    dbsession.commit()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.commit()

    dataset = DatasetFactory.create(
        name=MeasurementName.bundle_analysis_asset_size.value,
        repository_id=commit.repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.commit()

    class MockAssetReport:
        def __init__(self, mock_uuid, mock_size, mock_type):
            self.mock_uuid = mock_uuid
            self.mock_size = mock_size
            self.mock_type = mock_type

        @property
        def uuid(self):
            return self.mock_uuid

        @property
        def size(self):
            return self.mock_size

        @property
        def asset_type(self):
            return self.mock_type

    class MockBundleReport:
        def __init__(self, bundle_name, size):
            self.bundle_name = bundle_name
            self.size = size

        @property
        def name(self):
            return self.bundle_name

        def total_size(self):
            return self.size

        def asset_reports(self):
            return [
                MockAssetReport("UUID1", 123, AssetType.JAVASCRIPT),
                MockAssetReport("UUID2", 321, AssetType.JAVASCRIPT),
            ]

    class MockBundleAnalysisReport:
        def bundle_reports(self):
            return [MockBundleReport("BundleA", 1111)]

    mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
        return_value=MockBundleAnalysisReport(),
    )

    report_service = BundleAnalysisReportService(UserYaml.from_dict({}))
    result: ProcessingResult = report_service.save_measurements(commit, upload)

    assert result.error is None

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_asset_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="UUID1",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 123

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_asset_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="UUID2",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 321


@pytest.mark.asyncio
async def test_bundle_analysis_save_measurements_asset_type_sizes(
    dbsession, mocker, mock_storage
):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    commit = CommitFactory()
    dbsession.add(commit)
    dbsession.commit()

    commit_report = CommitReport(
        commit=commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(commit_report)
    dbsession.commit()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.commit()

    measurements_datasets = [
        MeasurementName.bundle_analysis_stylesheet_size,
        MeasurementName.bundle_analysis_font_size,
        MeasurementName.bundle_analysis_image_size,
        MeasurementName.bundle_analysis_javascript_size,
    ]
    for measurement in measurements_datasets:
        dataset = DatasetFactory.create(
            name=measurement.value,
            repository_id=commit.repository.repoid,
        )
        dbsession.add(dataset)
        dbsession.commit()

    class MockAssetReport:
        def __init__(self, mock_uuid, mock_size, mock_type):
            self.mock_uuid = mock_uuid
            self.mock_size = mock_size
            self.mock_type = mock_type

        @property
        def uuid(self):
            return self.mock_uuid

        @property
        def size(self):
            return self.mock_size

        @property
        def asset_type(self):
            return self.mock_type

    class MockBundleReport:
        def __init__(self, bundle_name, size):
            self.bundle_name = bundle_name
            self.size = size

        @property
        def name(self):
            return self.bundle_name

        def total_size(self):
            return self.size

        def asset_reports(self):
            return [
                MockAssetReport("UUID1", 111, AssetType.JAVASCRIPT),
                MockAssetReport("UUID2", 222, AssetType.FONT),
                MockAssetReport("UUID3", 333, AssetType.IMAGE),
                MockAssetReport("UUID4", 444, AssetType.STYLESHEET),
            ]

    class MockBundleAnalysisReport:
        def bundle_reports(self):
            return [MockBundleReport("BundleA", 1111)]

    mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
        return_value=MockBundleAnalysisReport(),
    )

    report_service = BundleAnalysisReportService(UserYaml.from_dict({}))
    result: ProcessingResult = report_service.save_measurements(commit, upload)

    assert result.error is None

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_javascript_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="BundleA",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 111

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_font_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="BundleA",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 222

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_image_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="BundleA",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 333

    measurements = (
        dbsession.query(Measurement)
        .filter_by(
            name=MeasurementName.bundle_analysis_stylesheet_size.value,
            commit_sha=commit.commitid,
            timestamp=commit.timestamp,
            measurable_id="BundleA",
        )
        .all()
    )

    assert len(measurements) == 1
    assert measurements[0].value == 444


@pytest.mark.asyncio
async def test_bundle_analysis_save_measurements_error(dbsession, mocker, mock_storage):
    storage_path = (
        "v1/repos/testing/ed1bdd67-8fd2-4cdb-ac9e-39b99e4a3892/bundle_report.sqlite"
    )
    mock_storage.write_file(get_bucket_name(), storage_path, "test-content")

    commit = CommitFactory()
    dbsession.add(commit)
    dbsession.commit()

    commit_report = CommitReport(
        commit=commit, report_type=ReportType.BUNDLE_ANALYSIS.value
    )
    dbsession.add(commit_report)
    dbsession.commit()

    upload = UploadFactory.create(storage_path=storage_path, report=commit_report)
    dbsession.add(upload)
    dbsession.commit()

    dataset = DatasetFactory.create(
        name=MeasurementName.bundle_analysis_asset_size.value,
        repository_id=commit.repository.repoid,
    )
    dbsession.add(dataset)
    dbsession.commit()

    mocker.patch(
        "shared.bundle_analysis.BundleAnalysisReportLoader.load",
        return_value=None,
    )

    report_service = BundleAnalysisReportService(UserYaml.from_dict({}))
    result: ProcessingResult = report_service.save_measurements(commit, upload)

    assert result.error is not None
