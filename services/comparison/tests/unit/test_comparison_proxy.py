from mock import call, patch

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.comparison import NOT_RESOLVED, ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.repository import EnrichedPull


def make_sample_comparison(adjusted_base=False):
    repo = RepositoryFactory.create(owner__service="github")

    head_commit = CommitFactory.create(repository=repo)
    adjusted_base_commit = CommitFactory.create(repository=repo)

    if adjusted_base:
        # Just getting a random commitid, doesn't need to be in the db
        patch_coverage_base_commitid = CommitFactory.create(repository=repo).commitid
    else:
        patch_coverage_base_commitid = adjusted_base_commit.commitid

    pull = PullFactory.create(
        repository=repo,
        head=head_commit.commitid,
        base=patch_coverage_base_commitid,
        compared_to=adjusted_base_commit.commitid,
    )

    base_full_commit = FullCommit(commit=adjusted_base_commit, report=None)
    head_full_commit = FullCommit(commit=head_commit, report=None)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=patch_coverage_base_commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={},
            ),
        ),
    )


class TestComparisonProxy(object):
    compare_url = "https://api.github.com/repos/{}/compare/{}...{}"

    @patch("shared.torngit.github.Github.get_compare")
    def test_get_diff_adjusted_base(self, mock_get_compare):
        comparison = make_sample_comparison(adjusted_base=True)
        mock_get_compare.return_value = {"diff": "magic string"}
        result = comparison.get_diff(use_original_base=False)

        assert result == "magic string"
        assert comparison._adjusted_base_diff == "magic string"
        assert comparison._original_base_diff is NOT_RESOLVED
        assert (
            comparison.comparison.patch_coverage_base_commitid
            != comparison.project_coverage_base.commit.commitid
        )

        assert mock_get_compare.call_args_list == [
            call(
                comparison.project_coverage_base.commit.commitid,
                comparison.head.commit.commitid,
                with_commits=False,
            ),
        ]

    @patch("shared.torngit.github.Github.get_compare")
    def test_get_diff_original_base(self, mock_get_compare):
        comparison = make_sample_comparison(adjusted_base=True)
        mock_get_compare.return_value = {"diff": "magic string"}
        result = comparison.get_diff(use_original_base=True)

        assert result == "magic string"
        assert comparison._original_base_diff == "magic string"
        assert comparison._adjusted_base_diff is NOT_RESOLVED
        assert (
            comparison.comparison.patch_coverage_base_commitid
            != comparison.project_coverage_base.commit.commitid
        )

        assert mock_get_compare.call_args_list == [
            call(
                comparison.comparison.patch_coverage_base_commitid,
                comparison.head.commit.commitid,
                with_commits=False,
            ),
        ]

    @patch("shared.torngit.github.Github.get_compare")
    def test_get_diff_bases_match_original_base(self, mock_get_compare):
        comparison = make_sample_comparison(adjusted_base=False)
        mock_get_compare.return_value = {"diff": "magic string"}
        result = comparison.get_diff(use_original_base=True)

        assert result == "magic string"
        assert comparison._original_base_diff == "magic string"
        assert (
            comparison.comparison.patch_coverage_base_commitid
            == comparison.project_coverage_base.commit.commitid
        )

        # In this test case, the adjusted and original base commits are the
        # same. If we get one, we should set the cache for the other.
        adjusted_base_result = comparison.get_diff(use_original_base=False)
        assert comparison._adjusted_base_diff == "magic string"

        # Make sure we only called the Git provider API once
        assert mock_get_compare.call_args_list == [
            call(
                comparison.comparison.patch_coverage_base_commitid,
                comparison.head.commit.commitid,
                with_commits=False,
            ),
        ]

    @patch("shared.torngit.github.Github.get_compare")
    def test_get_diff_bases_match_adjusted_base(self, mock_get_compare):
        comparison = make_sample_comparison(adjusted_base=False)
        mock_get_compare.return_value = {"diff": "magic string"}
        result = comparison.get_diff(use_original_base=False)

        assert result == "magic string"
        assert comparison._adjusted_base_diff == "magic string"
        assert (
            comparison.comparison.patch_coverage_base_commitid
            == comparison.project_coverage_base.commit.commitid
        )

        # In this test case, the adjusted and original base commits are the
        # same. If we get one, we should set the cache for the other.
        adjusted_base_result = comparison.get_diff(use_original_base=True)
        assert comparison._adjusted_base_diff == "magic string"

        # Make sure we only called the Git provider API once
        assert mock_get_compare.call_args_list == [
            call(
                comparison.comparison.patch_coverage_base_commitid,
                comparison.head.commit.commitid,
                with_commits=False,
            ),
        ]
