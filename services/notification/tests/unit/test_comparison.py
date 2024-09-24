from shared.reports.types import Change

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

    def test_get_changes_rust_vs_python(self, mocker):
        mocker.patch.object(ComparisonProxy, "get_diff")
        mocker.patch(
            "services.comparison.get_changes",
            return_value=[Change(path="apple"), Change(path="pear")],
        )
        mocker.patch(
            "services.comparison.get_changes_using_rust",
            return_value=[Change(path="banana"), Change(path="pear")],
        )
        comparison = ComparisonProxy(mocker.MagicMock())
        res = comparison.get_changes()
        expected_result = [Change(path="apple"), Change(path="pear")]
        assert expected_result == res
