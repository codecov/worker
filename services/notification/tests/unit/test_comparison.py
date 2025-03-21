from services.comparison import ComparisonProxy, FilteredComparison


class TestFilteredComparison(object):
    def test_get_existing_statuses(self, mocker):
        mocked_get_existing_statuses = mocker.patch.object(
            ComparisonProxy, "get_existing_statuses"
        )
        flags, path_patterns = ["flag"], None
        comparison = ComparisonProxy(mocker.MagicMock())
        filtered_comparison = comparison.get_filtered_comparison(flags, path_patterns)
        assert isinstance(filtered_comparison, FilteredComparison)
        res = filtered_comparison.get_existing_statuses()
        assert res == mocked_get_existing_statuses.return_value
