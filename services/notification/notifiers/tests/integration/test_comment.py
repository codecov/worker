import pytest

from services.notification.notifiers.comment import CommentNotifier
from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.notification.types import FullCommit, Comparison, EnrichedPull
from services.notification.comparison import ComparisonProxy
from services.decoration import Decoration


@pytest.fixture
def sample_comparison(dbsession, request, sample_report, small_report):
    repository = RepositoryFactory.create(
        owner__username="ThiagoCodecov",
        name="example-python",
        owner__unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
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
    base_full_commit = FullCommit(commit=base_commit, report=small_report)
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "hootener",},
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
    base_full_commit = FullCommit(commit=base_commit, report=small_report)
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "falco.lombardi",},
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
        owner__username="1nf1n1t3l00p",
        name="priv_example",
        owner__unencrypted_oauth_token="test1p40fvqsw2hoxl55kvhd4sakchhehblihuth",
        image_token="abcdefghij",
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository, commitid="ca084b346c2f1450f011adbd5ec950e3532b57b6"
    )
    head_commit = CommitFactory.create(
        repository=repository,
        branch="featureA",
        commitid="6341a94d2bb77a6153cec905363348937d258720",
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
                    "author": {"id": "12345", "username": "1nf1n1t3l00p",},
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


class TestCommentNotifierIntegration(object):
    @pytest.mark.asyncio
    async def test_notify(self, sample_comparison, codecov_vcr):
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
            "> Merging [#15](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=desc) into [master](None/gh/ThiagoCodecov/example-python/commit/4535be18e90467d6d9a99c0ce651becec7f7eba6?el=desc) will **increase** coverage by `10.00%`.",
            "> The diff coverage is `n/a`.",
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
            "| [Impacted Files](None/gh/ThiagoCodecov/example-python/pull/15?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| [file\\_2.py](None/gh/ThiagoCodecov/example-python/pull/15/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
            "| [file\\_1.go](None/gh/ThiagoCodecov/example-python/pull/15/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <0.00%> (+12.50%)` | `10.00% <0.00%> (-1.00%)` | :arrow_up: |",
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
        self, dbsession, sample_comparison_for_upgrade, codecov_vcr
    ):
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
            "The author of this PR, 1nf1n1t3l00p, is not an activated member of this organization on Codecov.",
            "Please [activate this user on Codecov](None/account/gh/1nf1n1t3l00p/users) to display this PR comment.",
            "Coverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.",
            "Please don't hesitate to email us at success@codecov.io with any questions.",
        ]
        for exp, res in zip(result.data_sent["message"], expected_message):
            assert exp == res
        assert result.data_sent["message"] == expected_message
        assert result.data_sent == {
            "commentid": None,
            "message": expected_message,
            "pullid": 1,
        }
        assert result.data_received == {"id": 609479265}

    @pytest.mark.asyncio
    async def test_notify_gitlab(self, sample_comparison_gitlab, codecov_vcr):
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
            "> Merging [#11](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=desc) into [master](None/gl/l00p_group_1:subgroup1/proj-b/commit/842f7c86a5d383fee0ece8cf2a97a1d8cdfeb7d4?el=desc) will **increase** coverage by `10.00%`.",
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
            "| [Impacted Files](None/gl/l00p_group_1:subgroup1/proj-b/pull/11?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            "|---|---|---|---|",
            "| [file\\_2.py](None/gl/l00p_group_1:subgroup1/proj-b/pull/11/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
            "| [file\\_1.go](None/gl/l00p_group_1:subgroup1/proj-b/pull/11/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <0.00%> (+12.50%)` | `10.00% <0.00%> (-1.00%)` | :arrow_up: |",
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
