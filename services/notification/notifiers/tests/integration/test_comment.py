from unittest.mock import PropertyMock

import pytest
from shared.reports.readonly import ReadOnlyReport

from database.enums import TestResultsProcessingError
from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.comparison import ComparisonContext, ComparisonProxy
from services.comparison.types import Comparison, EnrichedPull, FullCommit
from services.decoration import Decoration
from services.notification.notifiers.comment import CommentNotifier


@pytest.fixture
def is_not_first_pull(mocker):
    mocker.patch(
        "database.models.core.Pull.is_first_coverage_pull",
        return_value=False,
        new_callable=PropertyMock,
    )


@pytest.fixture
def codecove2e_comparison(dbsession, request, sample_report, small_report):
    repository = RepositoryFactory.create(
        owner__service="github",
        owner__username="codecove2e",
        name="example-python",
        owner__unencrypted_oauth_token="ghp_testxh25kbya8pcenroaxwqsiq23ff9xzr0u",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="93189ce50f224296d6412e2884b93dcc3c7c8654"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="new_branch",
        commitid="8589c19ce95a2b13cf7b3272cbf275ca9651ae9c",
    )
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        pullid=4,
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(small_report)
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=base_commit.commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecove2e"},
                    "base": {
                        "branch": "main",
                        "commitid": "93189ce50f224296d6412e2884b93dcc3c7c8654",
                    },
                    "head": {
                        "branch": "codecove2e-patch-3",
                        "commitid": "8589c19ce95a2b13cf7b3272cbf275ca9651ae9c",
                    },
                    "state": "open",
                    "title": "Update __init__.py",
                    "id": "4",
                    "number": "4",
                },
            ),
        )
    )


@pytest.fixture
def sample_comparison(dbsession, request, sample_report, small_report):
    repository = RepositoryFactory.create(
        owner__service="github",
        owner__username="joseph-sentry",
        name="codecov-demo",
        owner__unencrypted_oauth_token="ghp_testmgzs9qm7r27wp376fzv10aobbpva7hd3",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="5b174c2b40d501a70c479e91025d5109b1ad5c1b"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="test",
        commitid="5601846871b8142ab0df1e0b8774756c658bcc7d",
    )
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        pullid=9,
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(small_report)
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=base_commit.commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "joseph-sentry"},
                    "base": {
                        "branch": "main",
                        "commitid": "5b174c2b40d501a70c479e91025d5109b1ad5c1b",
                    },
                    "head": {
                        "branch": "test",
                        "commitid": "5601846871b8142ab0df1e0b8774756c658bcc7d",
                    },
                    "state": "open",
                    "title": "make change",
                    "id": "9",
                    "number": "9",
                },
            ),
        )
    )


@pytest.fixture
def sample_comparison_gitlab(dbsession, request, sample_report, small_report):
    repository = RepositoryFactory.create(
        owner__username="joseph-sentry",
        owner__service="gitlab",
        owner__unencrypted_oauth_token="test1nioqi3p3681oa43",
        service_id="47404140",
        name="example-python",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="0fc784af11c401449e56b24a174bae7b9af86c98"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="behind",
        commitid="0b6a213fc300cd328c0625f38f30432ee6e066e5",
    )
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        pullid=1,
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(small_report)
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=base_commit.commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "15014576", "username": "joseph-sentry"},
                    "base": {
                        "branch": "main",
                        "commitid": "0fc784af11c401449e56b24a174bae7b9af86c98",
                    },
                    "head": {
                        "branch": "behind",
                        "commitid": "0b6a213fc300cd328c0625f38f30432ee6e066e5",
                    },
                    "state": "open",
                    "title": "Behind",
                    "id": "1",
                    "number": "1",
                },
            ),
        )
    )


@pytest.fixture
def sample_comparison_for_upgrade(dbsession, request, sample_report, small_report):
    repository = RepositoryFactory.create(
        owner__service="github",
        owner__username="codecove2e",
        name="example-python",
        owner__unencrypted_oauth_token="ghp_testgkdo1u8jqexy9wabk1n0puoetf9ziam5",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="93189ce50f224296d6412e2884b93dcc3c7c8654"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="new_branch",
        commitid="8589c19ce95a2b13cf7b3272cbf275ca9651ae9c",
    )
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        pullid=4,
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(small_report)
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=base_commit.commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecove2e"},
                    "base": {
                        "branch": "master",
                        "commitid": "93189ce50f224296d6412e2884b93dcc3c7c8654",
                    },
                    "head": {
                        "branch": "codecove2e-patch-3",
                        "commitid": "8589c19ce95a2b13cf7b3272cbf275ca9651ae9c",
                    },
                    "state": "open",
                    "title": "Update __init__.py",
                    "id": "4",
                    "number": "4",
                },
            ),
        )
    )


@pytest.fixture
def sample_comparison_for_limited_upload(
    dbsession, request, sample_report, small_report
):
    repository = RepositoryFactory.create(
        owner__username="test-acc9",
        owner__service="github",
        name="priv_example",
        owner__unencrypted_oauth_token="ghp_test1xwr5rxl12dbm97a7r4anr6h67uw0thf",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="ef6edf5ae6643d53a7971fb8823d3f7b2ac65619"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="featureA",
        commitid="610ada9fa2bbc49f1a08917da3f73bef2d03709c",
    )
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        pullid=1,
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(commit=base_commit, report=small_report)
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=base_commit.commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "dana-yaish"},
                    "base": {
                        "branch": "main",
                        "commitid": "ef6edf5ae6643d53a7971fb8823d3f7b2ac65619",
                    },
                    "head": {
                        "branch": "featureA",
                        "commitid": "610ada9fa2bbc49f1a08917da3f73bef2d03709c",
                    },
                    "state": "open",
                    "title": "Create randomcommit.me",
                    "id": "1",
                    "number": "1",
                },
            ),
        )
    )


@pytest.mark.usefixtures("is_not_first_pull")
class TestCommentNotifierIntegration(object):
    def test_notify(self, sample_comparison, codecov_vcr, mock_configuration):
        sample_comparison.context = ComparisonContext(
            all_tests_passed=True, test_results_error=None
        )
        mock_configuration._params["setup"] = {
            "codecov_url": None,
            "codecov_dashboard_url": None,
        }
        comparison = sample_comparison
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "## [Codecov](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=h1) Report",
            "All modified and coverable lines are covered by tests :white_check_mark:",
            "> Project coverage is 60.00%. Comparing base [(`5b174c2`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5b174c2b40d501a70c479e91025d5109b1ad5c1b?dropdown=coverage&el=desc) to head [(`5601846`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5601846871b8142ab0df1e0b8774756c658bcc7d?dropdown=coverage&el=desc).",
            "> Report is 2 commits behind head on main.",
            "",
            ":white_check_mark: All tests successful. No failed tests found.",
            "",
            ":exclamation: Your organization needs to install the [Codecov GitHub app](https://github.com/apps/codecov/installations/select_target) to enable full functionality.",
            "",
            "[![Impacted file tree graph](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##               main       #9       +/-   ##",
            "=============================================",
            "+ Coverage     50.00%   60.00%   +10.00%     ",
            "+ Complexity       11       10        -1     ",
            "=============================================",
            "  Files             2        2               ",
            "  Lines             6       10        +4     ",
            "  Branches          0        1        +1     ",
            "=============================================",
            "+ Hits              3        6        +3     ",
            "  Misses            3        3               ",
            "- Partials          0        1        +1     ",
            "```",
            "",
            "| [Flag](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flags) | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| [integration](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `?` | `?` | |",
            "| [unit](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/indirect-changes?src=pr&el=tree-more)",
            "",
            "------",
            "",
            "[Continue to review full report in Codecov by Sentry](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=continue).",
            "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)",
            "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            "> Powered by [Codecov](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=footer). Last update [5b174c2...5601846](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=lastupdated). Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res
        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 9}
        assert result.data_received == {"id": 1699669247}

    def test_notify_test_results_error(
        self, sample_comparison, codecov_vcr, mock_configuration
    ):
        sample_comparison.context = ComparisonContext(
            all_tests_passed=False,
            test_results_error=TestResultsProcessingError.NO_SUCCESS,
        )
        mock_configuration._params["setup"] = {
            "codecov_url": None,
            "codecov_dashboard_url": None,
        }
        comparison = sample_comparison
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "## [Codecov](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=h1) Report",
            "All modified and coverable lines are covered by tests :white_check_mark:",
            "> Project coverage is 60.00%. Comparing base [(`5b174c2`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5b174c2b40d501a70c479e91025d5109b1ad5c1b?dropdown=coverage&el=desc) to head [(`5601846`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5601846871b8142ab0df1e0b8774756c658bcc7d?dropdown=coverage&el=desc).",
            "> Report is 2 commits behind head on main.",
            "",
            ":x: We are unable to process any of the uploaded JUnit XML files. Please ensure your files are in the right format.",
            "",
            ":exclamation: Your organization needs to install the [Codecov GitHub app](https://github.com/apps/codecov/installations/select_target) to enable full functionality.",
            "",
            "[![Impacted file tree graph](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##               main       #9       +/-   ##",
            "=============================================",
            "+ Coverage     50.00%   60.00%   +10.00%     ",
            "+ Complexity       11       10        -1     ",
            "=============================================",
            "  Files             2        2               ",
            "  Lines             6       10        +4     ",
            "  Branches          0        1        +1     ",
            "=============================================",
            "+ Hits              3        6        +3     ",
            "  Misses            3        3               ",
            "- Partials          0        1        +1     ",
            "```",
            "",
            "| [Flag](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flags) | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| [integration](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `?` | `?` | |",
            "| [unit](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/indirect-changes?src=pr&el=tree-more)",
            "",
            "------",
            "",
            "[Continue to review full report in Codecov by Sentry](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=continue).",
            "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)",
            "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            "> Powered by [Codecov](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=footer). Last update [5b174c2...5601846](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=lastupdated). Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res
        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 9}
        assert result.data_received == {"id": 1699669247}

    def test_notify_upgrade(
        self, dbsession, sample_comparison_for_upgrade, codecov_vcr, mock_configuration
    ):
        mock_configuration._params["setup"] = {"codecov_dashboard_url": None}
        comparison = sample_comparison_for_upgrade
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.upgrade,
        )
        result = notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        expected_message = [
            "The author of this PR, codecove2e, is not an activated member of this organization on Codecov.",
            "Please [activate this user on Codecov](https://app.codecov.io/members/gh/codecove2e) to display this PR comment.",
            "Coverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.",
            "Please don't hesitate to email us at support@codecov.io with any questions.",
        ]
        for exp, res in zip(result.data_sent["message"], expected_message):
            assert exp == res
        assert result.data_sent["message"] == expected_message
        assert result.data_sent == {
            "commentid": None,
            "message": expected_message,
            "pullid": 4,
        }
        assert result.data_received == {"id": 1361234119}

    def test_notify_upload_limited(
        self,
        dbsession,
        sample_comparison_for_limited_upload,
        codecov_vcr,
        mock_configuration,
    ):
        mock_configuration._params["setup"] = {
            "codecov_url": None,
            "codecov_dashboard_url": "https://app.codecov.io",
        }
        comparison = sample_comparison_for_limited_upload
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.upload_limit,
        )
        result = notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        expected_message = [
            "## [Codecov](https://app.codecov.io/plan/gh/test-acc9) upload limit reached :warning:",
            "This org is currently on the free Basic Plan; which includes 250 free private repo uploads each rolling month.\
                 This limit has been reached and additional reports cannot be generated. For unlimited uploads,\
                      upgrade to our [pro plan](https://app.codecov.io/plan/gh/test-acc9).",
            "",
            "**Do you have questions or need help?** Connect with our sales team today at ` sales@codecov.io `",
        ]
        for exp, res in zip(result.data_sent["message"], expected_message):
            assert exp == res
        assert result.data_sent["message"] == expected_message
        assert result.data_sent == {
            "commentid": None,
            "message": expected_message,
            "pullid": 1,
        }
        assert result.data_received == {"id": 1111984446}

    def test_notify_gitlab(
        self, sample_comparison_gitlab, codecov_vcr, mock_configuration
    ):
        mock_configuration._params["setup"] = {
            "codecov_url": None,
            "codecov_dashboard_url": None,
        }
        comparison = sample_comparison_gitlab
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "## [Codecov](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1?dropdown=coverage&src=pr&el=h1) Report",
            "All modified and coverable lines are covered by tests :white_check_mark:",
            "> Project coverage is 60.00%. Comparing base [(`0fc784a`)](https://app.codecov.io/gl/joseph-sentry/example-python/commit/0fc784af11c401449e56b24a174bae7b9af86c98?dropdown=coverage&el=desc) to head [(`0b6a213`)](https://app.codecov.io/gl/joseph-sentry/example-python/commit/0b6a213fc300cd328c0625f38f30432ee6e066e5?dropdown=coverage&el=desc).",
            "",
            "[![Impacted file tree graph](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##               main       #1       +/-   ##",
            "=============================================",
            "+ Coverage     50.00%   60.00%   +10.00%     ",
            "+ Complexity       11       10        -1     ",
            "=============================================",
            "  Files             2        2               ",
            "  Lines             6       10        +4     ",
            "  Branches          0        1        +1     ",
            "=============================================",
            "+ Hits              3        6        +3     ",
            "  Misses            3        3               ",
            "- Partials          0        1        +1     ",
            "```",
            "",
            "| [Flag](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1/flags?src=pr&el=flags) | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| [integration](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1/flags?src=pr&el=flag) | `?` | `?` | |",
            "| [unit](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1/flags?src=pr&el=flag) | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1/indirect-changes?src=pr&el=tree-more)",
            "",
            "------",
            "",
            "[Continue to review full report in Codecov by Sentry](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1?dropdown=coverage&src=pr&el=continue).",
            "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)",
            "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            "> Powered by [Codecov](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1?dropdown=coverage&src=pr&el=footer). Last update [0fc784a...0b6a213](https://app.codecov.io/gl/joseph-sentry/example-python/pull/1?dropdown=coverage&src=pr&el=lastupdated). Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res
        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 1}
        assert result.data_received == {"id": 1457135397}

    def test_notify_new_layout(
        self, sample_comparison, codecov_vcr, mock_configuration
    ):
        mock_configuration._params["setup"] = {"codecov_dashboard_url": None}
        comparison = sample_comparison
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "newheader, reach, diff, flags, files, newfooter",
                "hide_comment_details": True,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "## [Codecov](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=h1) Report",
            "All modified and coverable lines are covered by tests :white_check_mark:",
            "> Project coverage is 60.00%. Comparing base [(`5b174c2`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5b174c2b40d501a70c479e91025d5109b1ad5c1b?dropdown=coverage&el=desc) to head [(`5601846`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5601846871b8142ab0df1e0b8774756c658bcc7d?dropdown=coverage&el=desc).",
            "> Report is 2 commits behind head on main.",
            "",
            ":exclamation: Your organization needs to install the [Codecov GitHub app](https://github.com/apps/codecov/installations/select_target) to enable full functionality.",
            "",
            "<details><summary>Additional details and impacted files</summary>\n",
            "",
            "[![Impacted file tree graph](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##               main       #9       +/-   ##",
            "=============================================",
            "+ Coverage     50.00%   60.00%   +10.00%     ",
            "+ Complexity       11       10        -1     ",
            "=============================================",
            "  Files             2        2               ",
            "  Lines             6       10        +4     ",
            "  Branches          0        1        +1     ",
            "=============================================",
            "+ Hits              3        6        +3     ",
            "  Misses            3        3               ",
            "- Partials          0        1        +1     ",
            "```",
            "",
            "| [Flag](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flags) | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| [integration](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `?` | `?` | |",
            "| [unit](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/indirect-changes?src=pr&el=tree-more)",
            "",
            "</details>",
            "",
            "[:umbrella: View full report in Codecov by Sentry](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=continue).   ",
            ":loudspeaker: Have feedback on the report? [Share it here](https://about.codecov.io/codecov-pr-comment-feedback/).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res

        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 9}
        assert result.data_received == {"id": 1699669290}

    def test_notify_with_components(
        self, sample_comparison, codecov_vcr, mock_configuration
    ):
        mock_configuration._params["setup"] = {"codecov_dashboard_url": None}
        comparison = sample_comparison
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "newheader, reach, diff, flags, files, components, newfooter",
                "hide_comment_details": True,
            },
            notifier_site_settings=True,
            current_yaml={
                "component_management": {
                    "individual_components": [
                        {"component_id": "go_files", "paths": [r".*\.go"]}
                    ]
                }
            },
        )
        result = notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "## [Codecov](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=h1) Report",
            "All modified and coverable lines are covered by tests :white_check_mark:",
            "> Project coverage is 60.00%. Comparing base [(`5b174c2`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5b174c2b40d501a70c479e91025d5109b1ad5c1b?dropdown=coverage&el=desc) to head [(`5601846`)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/commit/5601846871b8142ab0df1e0b8774756c658bcc7d?dropdown=coverage&el=desc).",
            "> Report is 2 commits behind head on main.",
            "",
            ":exclamation: Your organization needs to install the [Codecov GitHub app](https://github.com/apps/codecov/installations/select_target) to enable full functionality.",
            "",
            "<details><summary>Additional details and impacted files</summary>\n",
            "",
            "[![Impacted file tree graph](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##               main       #9       +/-   ##",
            "=============================================",
            "+ Coverage     50.00%   60.00%   +10.00%     ",
            "+ Complexity       11       10        -1     ",
            "=============================================",
            "  Files             2        2               ",
            "  Lines             6       10        +4     ",
            "  Branches          0        1        +1     ",
            "=============================================",
            "+ Hits              3        6        +3     ",
            "  Misses            3        3               ",
            "- Partials          0        1        +1     ",
            "```",
            "",
            "| [Flag](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flags) | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| [integration](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `?` | `?` | |",
            "| [unit](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/flags?src=pr&el=flag) | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/indirect-changes?src=pr&el=tree-more)",
            "",
            "| [Components](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/components?src=pr&el=components) | Coverage Δ | |",
            "|---|---|---|",
            "| [go_files](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9/components?src=pr&el=component) | `62.50% <ø> (+12.50%)` | :arrow_up: |",
            "",
            "</details>",
            "",
            "[:umbrella: View full report in Codecov by Sentry](https://app.codecov.io/gh/joseph-sentry/codecov-demo/pull/9?dropdown=coverage&src=pr&el=continue).   ",
            ":loudspeaker: Have feedback on the report? [Share it here](https://about.codecov.io/codecov-pr-comment-feedback/).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res

        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 9}
        assert result.data_received == {"id": 1699669323}
