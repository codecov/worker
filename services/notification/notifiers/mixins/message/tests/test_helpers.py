import pytest
from shared.reports.resources import Report, ReportTotals

from services.comparison import ComparisonProxy
from services.notification.notifiers.mixins.message.helpers import (
    has_project_status,
    is_coverage_drop_significant,
)


@pytest.mark.parametrize(
    "yaml, expected",
    [
        pytest.param(
            {"coverage": {"status": {"project": False}}},
            False,
            id="project_coverage_boolean_disabled",
        ),
        pytest.param(
            {"coverage": {"status": {"project": True}}},
            True,
            id="project_coverage_boolean_enabled",
        ),
        pytest.param(
            {"coverage": {"status": {"project": {"enabled": True}}}},
            True,
            id="project_coverage_dict_enabled",
        ),
        pytest.param(
            {"coverage": {"status": {"project": {"enabled": False}}}},
            False,
            id="project_coverage_dict_disabled",
        ),
        pytest.param(
            {
                "coverage": {
                    "status": {"project": {"only_pulls": True, "informational": True}}
                }
            },
            True,
            id="project_coverage_dict_no_explicit_enabled_value",
        ),
        pytest.param(
            {"coverage": {"status": {"project": "enabled"}}},
            False,
            id="project_coverage_invalid_value",
        ),
    ],
)
def test_has_project_status(yaml: dict, expected: bool):
    assert has_project_status(yaml) == expected


@pytest.mark.parametrize(
    "head_coverage, base_coverage, expected",
    [
        pytest.param(None, None, False, id="no_head_no_base_not_significant_drop"),
        pytest.param(85.0, None, False, id="no_base_not_significant_drop"),
        pytest.param(None, 85.0, False, id="no_head_not_significant_drop"),
        pytest.param(85.0, 85.0, False, id="no_change"),
        pytest.param(91.0, 85.0, False, id="change_is_significant_but_positive"),
        pytest.param(86.0, 85.0, False, id="change_not_significant"),
        pytest.param(80.0, 85.0, True, id="change_is_significant"),
    ],
)
def test_is_coverage_drop_significant(
    head_coverage: float, base_coverage: float, expected, mocker
):
    head_report = Report()
    head_report._totals = ReportTotals(coverage=head_coverage)
    base_report = Report()
    base_report._totals = ReportTotals(coverage=base_coverage)
    mock_head = mocker.MagicMock(report=head_report)
    mock_base = mocker.MagicMock(report=base_report)
    mock_comparison = mocker.MagicMock(head=mock_head, project_coverage_base=mock_base)
    fake_comparison = ComparisonProxy(comparison=mock_comparison)
    assert is_coverage_drop_significant(fake_comparison) == expected
