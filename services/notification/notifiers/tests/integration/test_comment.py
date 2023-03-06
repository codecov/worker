from unittest.mock import patch

import pytest
from shared.reports.readonly import ReadOnlyReport

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, EnrichedPull, FullCommit
from services.decoration import Decoration
from services.notification.notifiers.comment import CommentNotifier


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
            base=base_full_commit,
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
def sample_comparison(dbsession, request, sample_report, small_report):
    repository = RepositoryFactory.create(
        owner__service="github",
        owner__username="ThiagoCodecov",
        name="example-python",
        owner__unencrypted_oauth_token="ghp_testmgzs9qm7r27wp376fzv10aobbpva7hd3",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="4535be18e90467d6d9a99c0ce651becec7f7eba6"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="new_branch",
        commitid="2e2600aa09525e2e1e1d98b09de61454d29c94bb",
    )
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        pullid=15,
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
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "hootener"},
                    "base": {
                        "branch": "master",
                        "commitid": "30cc1ed751a59fa9e7ad8e79fff41a6fe11ef5dd",
                    },
                    "head": {
                        "branch": "thiago/test-1",
                        "commitid": "2e2600aa09525e2e1e1d98b09de61454d29c94bb",
                    },
                    "state": "open",
                    "title": "Thiago/test 1",
                    "id": "15",
                    "number": "15",
                },
            ),
        )
    )


@pytest.fixture
def sample_comparison_gitlab(dbsession, request, sample_report, small_report):
    repository = RepositoryFactory.create(
        owner__username="l00p_group_1:subgroup1",
        owner__service="gitlab",
        owner__unencrypted_oauth_token="test1nioqi3p3681oa43",
        service_id="11087339",
        name="proj-b",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="842f7c86a5d383fee0ece8cf2a97a1d8cdfeb7d4"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="div",
        commitid="46ce216948fe8c301fc80d9ba3ba1a582a0ba497",
    )
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        pullid=11,
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
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "falco.lombardi"},
                    "base": {
                        "branch": "master",
                        "commitid": "842f7c86a5d383fee0ece8cf2a97a1d8cdfeb7d4",
                    },
                    "head": {
                        "branch": "div",
                        "commitid": "46ce216948fe8c301fc80d9ba3ba1a582a0ba497",
                    },
                    "state": "open",
                    "title": "Add div method",
                    "id": "11",
                    "number": "11",
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
            base=base_full_commit,
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
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "dana-yaish"},
                    "base": {
                        "branch": "master",
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


class TestCommentNotifierIntegration(object):
    @pytest.mark.asyncio
    async def test_notify(self, sample_comparison, codecov_vcr, mock_configuration):
        mock_configuration._params["setup"] = {"codecov_url": None}
        comparison = sample_comparison
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "# [Codecov](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=h1) Report",
            "> Merging [#15](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=desc) (2e2600a) into [master](None/gh/ThiagoCodecov/example-python/commit/4535be18e90467d6d9a99c0ce651becec7f7eba6?el=desc) (4535be1) will **increase** coverage by `10.00%`.",
            "> The diff coverage is `n/a`.",
            "",
            ":mega: This organization is not using Codecov’s [GitHub App Integration](https://github.com/apps/codecov). We recommend you install it so Codecov can continue to function properly for your repositories. [Learn more](https://about.codecov.io/blog/codecov-is-updating-its-github-integration/?utm_medium=prcomment)",
            "",
            "[![Impacted file tree graph](None/gh/ThiagoCodecov/example-python/pull/15/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##             master      #15       +/-   ##",
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
            "| Flag | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| integration | `?` | `?` | |",
            "| unit | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](None/gh/ThiagoCodecov/example-python/pull/15/indirect-changes?src=pr&el=tree-more)",
            "",
            "------",
            "",
            "[Continue to review full report at Codecov](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=continue).",
            "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)",
            "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            "> Powered by [Codecov](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=footer). Last update [30cc1ed...2e2600a](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=lastupdated). Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res
        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 15}
        assert result.data_received == {"id": 570682170}

    @pytest.mark.asyncio
    async def test_notify_upgrade(
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
        result = await notifier.notify(comparison)
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

    @pytest.mark.asyncio
    async def test_notify_upload_limited(
        self,
        dbsession,
        sample_comparison_for_limited_upload,
        codecov_vcr,
        mock_configuration,
    ):
        mock_configuration._params["setup"] = {
            "codecov_url": None,
            "codecov_dashboard_url": "test.example.br",
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
        result = await notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        expected_message = [
            f"# [Codecov](test.example.br/plan/gh/test-acc9) upload limit reached :warning:",
            f"This org is currently on the free Basic Plan; which includes 250 free private repo uploads each rolling month.\
                 This limit has been reached and additional reports cannot be generated. For unlimited uploads,\
                      upgrade to our [pro plan](test.example.br/plan/gh/test-acc9).",
            f"",
            f"**Do you have questions or need help?** Connect with our sales team today at ` sales@codecov.io `",
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

    @pytest.mark.asyncio
    async def test_notify_gitlab(
        self, sample_comparison_gitlab, codecov_vcr, mock_configuration
    ):
        mock_configuration._params["setup"] = {"codecov_url": None}
        comparison = sample_comparison_gitlab
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "# [Codecov](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=h1) Report",
            "> Merging [#11](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=desc) (46ce216) into [master](None/gl/l00p_group_1:subgroup1/proj-b/commit/842f7c86a5d383fee0ece8cf2a97a1d8cdfeb7d4?el=desc) (842f7c8) will **increase** coverage by `10.00%`.",
            "> The diff coverage is `n/a`.",
            "",
            "[![Impacted file tree graph](None/gl/l00p_group_1:subgroup1/proj-b/pull/11/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##             master      #11       +/-   ##",
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
            "| Flag | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| integration | `?` | `?` | |",
            "| unit | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](None/gl/l00p_group_1:subgroup1/proj-b/pull/11/indirect-changes?src=pr&el=tree-more)",
            "",
            "------",
            "",
            "[Continue to review full report at Codecov](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=continue).",
            "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)",
            "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            "> Powered by [Codecov](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=footer). Last update [842f7c8...46ce216](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=lastupdated). Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res
        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 11}
        assert result.data_received == {"id": 305215656}

    @pytest.mark.asyncio
    async def test_notify_new_layout(
        self, sample_comparison, codecov_vcr, mock_configuration
    ):
        mock_configuration._params["setup"] = {"codecov_url": None}
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
        result = await notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "# [Codecov](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=h1) Report",
            "Patch coverage has no change and project coverage change: **`+10.00`** :tada:",
            "> Comparison is base [(`4535be1`)](None/gh/ThiagoCodecov/example-python/commit/4535be18e90467d6d9a99c0ce651becec7f7eba6?el=desc) 50.00% compared to head [(`2e2600a`)](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=desc) 60.00%.",
            "",
            ":mega: This organization is not using Codecov’s [GitHub App Integration](https://github.com/apps/codecov). We recommend you install it so Codecov can continue to function properly for your repositories. [Learn more](https://about.codecov.io/blog/codecov-is-updating-its-github-integration/?utm_medium=prcomment)",
            "",
            "<details><summary>Additional details and impacted files</summary>\n",
            "",
            "[![Impacted file tree graph](None/gh/ThiagoCodecov/example-python/pull/15/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##             master      #15       +/-   ##",
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
            "| Flag | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| integration | `?` | `?` | |",
            "| unit | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](None/gh/ThiagoCodecov/example-python/pull/15/indirect-changes?src=pr&el=tree-more)",
            "",
            "</details>",
            "",
            "[:umbrella: View full report at Codecov](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=continue).   ",
            ":loudspeaker: Do you have feedback about the report comment? [Let us know in this issue](https://about.codecov.io/codecov-pr-comment-feedback/).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res

        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 15}
        assert result.data_received == {"id": 1069392024}

    @pytest.mark.asyncio
    async def test_notify_with_components(
        self, codecove2e_comparison, codecov_vcr, mock_configuration
    ):
        mock_configuration._params["setup"] = {"codecov_url": None}
        comparison = codecove2e_comparison
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
        result = await notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        message = [
            "# [Codecov](None/gh/codecove2e/example-python/pull/4?src=pr&el=h1) Report",
            "Patch coverage has no change and project coverage change: **`+10.00`** :tada:",
            "> Comparison is base [(`93189ce`)](None/gh/codecove2e/example-python/commit/93189ce50f224296d6412e2884b93dcc3c7c8654?el=desc) 50.00% compared to head [(`8589c19`)](None/gh/codecove2e/example-python/pull/4?src=pr&el=desc) 60.00%.",
            "",
            ":mega: This organization is not using Codecov’s [GitHub App Integration](https://github.com/apps/codecov). We recommend you install it so Codecov can continue to function properly for your repositories. [Learn more](https://about.codecov.io/blog/codecov-is-updating-its-github-integration/?utm_medium=prcomment)",
            "",
            "<details><summary>Additional details and impacted files</summary>\n",
            "",
            "[![Impacted file tree graph](None/gh/codecove2e/example-python/pull/4/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](None/gh/codecove2e/example-python/pull/4?src=pr&el=tree)",
            "",
            "```diff",
            "@@              Coverage Diff              @@",
            "##             master       #4       +/-   ##",
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
            "| Flag | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| integration | `?` | `?` | |",
            "| unit | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            "",
            "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            "",
            "[see 2 files with indirect coverage changes](None/gh/codecove2e/example-python/pull/4/indirect-changes?src=pr&el=tree-more)",
            "",
            "| Components | Coverage Δ | |",
            "|---|---|---|",
            "| go_files | `62.50% <ø> (+12.50%)` | :arrow_up: |",
            "",
            "</details>",
            "",
            "[:umbrella: View full report at Codecov](None/gh/codecove2e/example-python/pull/4?src=pr&el=continue).   ",
            ":loudspeaker: Do you have feedback about the report comment? [Let us know in this issue](https://about.codecov.io/codecov-pr-comment-feedback/).",
            "",
        ]
        for exp, res in zip(result.data_sent["message"], message):
            assert exp == res

        assert result.data_sent["message"] == message
        assert result.data_sent == {"commentid": None, "message": message, "pullid": 4}
        assert result.data_received == {"id": 1253851153}
