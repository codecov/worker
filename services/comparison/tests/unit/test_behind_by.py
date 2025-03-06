from shared.torngit.exceptions import TorngitClientGeneralError

from services.comparison import ComparisonProxy


class TestGetBehindBy(object):
    def test_get_behind_by(self, mocker, mock_repo_provider):
        comparison = ComparisonProxy(mocker.MagicMock())
        comparison.comparison.enriched_pull.provider_pull = {"base": {"branch": "a"}}
        mock_repo_provider.get_branches.return_value = [("a", "1")]
        mock_repo_provider.get_distance_in_commits.return_value = {
            "behind_by": 3,
            "behind_by_commit": 123456,
        }
        mocker.patch(
            "services.comparison.get_repo_provider_service",
            return_value=mock_repo_provider,
        )
        res = comparison.get_behind_by()
        assert res == 3

    def test_get_behind_by_no_base_commit(self, mocker):
        comparison = ComparisonProxy(mocker.MagicMock())
        del comparison.comparison.project_coverage_base.commit.commitid
        res = comparison.get_behind_by()
        assert res is None

    def test_get_behind_by_no_provider_pull(self, mocker):
        comparison = ComparisonProxy(mocker.MagicMock())
        comparison.comparison.enriched_pull.provider_pull = None
        res = comparison.get_behind_by()
        assert res is None

    def test_get_behind_by_no_matching_branches(self, mocker, mock_repo_provider):
        mock_repo_provider.get_branch.side_effect = TorngitClientGeneralError(
            404,
            None,
            "Branch not found",
        )
        mocker.patch(
            "services.comparison.get_repo_provider_service",
            return_value=mock_repo_provider,
        )
        comparison = ComparisonProxy(mocker.MagicMock())
        res = comparison.get_behind_by()
        assert res is None
