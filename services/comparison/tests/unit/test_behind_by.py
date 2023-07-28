import pytest

from services.comparison import ComparisonProxy


class TestGetBehindBy(object):
    @pytest.mark.asyncio
    async def test_get_behind_by(self, mocker, mock_repo_provider):
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
        res = await comparison.get_behind_by()
        assert res == 3

    @pytest.mark.asyncio
    async def test_get_behind_by_no_base_commit(self, mocker):
        comparison = ComparisonProxy(mocker.MagicMock())
        del comparison.comparison.base.commit.commitid
        res = await comparison.get_behind_by()
        assert res is None

    @pytest.mark.asyncio
    async def test_get_behind_by_no_provider_pull(self, mocker):
        comparison = ComparisonProxy(mocker.MagicMock())
        comparison.comparison.enriched_pull.provider_pull = None
        res = await comparison.get_behind_by()
        assert res is None

    @pytest.mark.asyncio
    async def test_get_behind_by_no_matching_branches(self, mocker, mock_repo_provider):
        mock_repo_provider.get_branches.return_value = []
        mocker.patch(
            "services.comparison.get_repo_provider_service",
            return_value=mock_repo_provider,
        )
        comparison = ComparisonProxy(mocker.MagicMock())
        res = await comparison.get_behind_by()
        assert res is None
