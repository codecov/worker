from typing import Dict, List

import pytest
from shared.validation.types import (
    CoverageCommentRequiredChanges,
    CoverageCommentRequiredChangesANDGroup,
)
from shared.yaml import UserYaml

from database.models.core import Repository
from services.comparison import ComparisonProxy
from services.notification.notifiers.comment import CommentNotifier
from services.notification.notifiers.comment.conditions import HasEnoughRequiredChanges


def _get_notifier(
    repository: Repository, required_changes: CoverageCommentRequiredChangesANDGroup
):
    return CommentNotifier(
        repository=repository,
        title="title",
        notifier_yaml_settings={"require_changes": required_changes},
        notifier_site_settings=True,
        current_yaml={},
    )


def _get_mock_compare_result(file_affected: str, lines_affected: List[str]) -> Dict:
    return {
        "diff": {
            "files": {
                file_affected: {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": lines_affected,
                            "lines": [
                                " Overview",
                                " --------",
                                " ",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "+",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                " ",
                                " .. code-block:: shell-session",
                                " ",
                            ],
                        },
                    ],
                    "stats": {"added": 3, "removed": 3},
                }
            }
        }
    }


@pytest.mark.parametrize(
    "comparison_name, condition, expected",
    [
        pytest.param(
            "sample_comparison",
            [CoverageCommentRequiredChanges.any_change.value],
            True,
            id="any_change_comparison_with_changes",
        ),
        pytest.param(
            "sample_comparison_without_base_report",
            [CoverageCommentRequiredChanges.any_change.value],
            False,
            id="any_change_comparison_without_base",
        ),
        pytest.param(
            "sample_comparison_no_change",
            [CoverageCommentRequiredChanges.any_change.value],
            False,
            id="any_change_sample_comparison_no_change",
        ),
        pytest.param(
            "sample_comparison",
            [CoverageCommentRequiredChanges.coverage_drop.value],
            False,
            id="coverage_drop_comparison_with_positive_changes",
        ),
        pytest.param(
            "sample_comparison_no_change",
            [CoverageCommentRequiredChanges.coverage_drop.value],
            False,
            id="coverage_drop_sample_comparison_no_change",
        ),
        pytest.param(
            "sample_comparison_without_base_report",
            [CoverageCommentRequiredChanges.coverage_drop.value],
            True,
            id="coverage_drop_comparison_without_base",
        ),
    ],
)
def test_condition_different_comparisons_no_diff(
    comparison_name, condition, expected, mock_repo_provider, request
):
    comparison = request.getfixturevalue(comparison_name)
    # There's no diff between HEAD and BASE so we can't calculate unexpected coverage.
    # Any change then needs to be a coverage change
    mock_repo_provider.get_compare.return_value = {"diff": {"files": {}, "commits": []}}
    notifier = _get_notifier(comparison.head.commit.repository, condition)
    assert HasEnoughRequiredChanges.check_condition(notifier, comparison) == expected


@pytest.mark.parametrize(
    "condition, expected",
    [
        pytest.param(
            [CoverageCommentRequiredChanges.any_change.value], False, id="any_change"
        ),
        pytest.param(
            [CoverageCommentRequiredChanges.coverage_drop.value],
            False,
            id="coverage_drop",
        ),
        pytest.param(
            [CoverageCommentRequiredChanges.uncovered_patch.value],
            False,
            id="uncovered_patch",
        ),
        pytest.param(
            [CoverageCommentRequiredChanges.no_requirements.value],
            True,
            id="no_requirements",
        ),
    ],
)
def test_condition_exact_same_report_coverage_not_affected_by_diff(
    sample_comparison_no_change, mock_repo_provider, condition, expected
):
    mock_repo_provider.get_compare.return_value = _get_mock_compare_result(
        "README.md", ["5", "8", "5", "9"]
    )
    notifier = _get_notifier(
        sample_comparison_no_change.head.commit.repository, condition
    )
    assert (
        HasEnoughRequiredChanges.check_condition(notifier, sample_comparison_no_change)
        == expected
    )


@pytest.mark.parametrize(
    "condition, expected",
    [
        pytest.param(
            [CoverageCommentRequiredChanges.any_change.value], True, id="any_change"
        ),
        pytest.param(
            [CoverageCommentRequiredChanges.coverage_drop.value],
            False,
            id="coverage_drop",
        ),
        pytest.param(
            [CoverageCommentRequiredChanges.uncovered_patch.value],
            False,
            id="uncovered_patch",
        ),
        pytest.param(
            [CoverageCommentRequiredChanges.no_requirements.value],
            True,
            id="no_requirements",
        ),
    ],
)
def test_condition_exact_same_report_coverage_affected_by_diff(
    sample_comparison_no_change, mock_repo_provider, condition, expected
):
    mock_repo_provider.get_compare.return_value = _get_mock_compare_result(
        "file_1.go", ["4", "8", "4", "8"]
    )
    notifier = _get_notifier(
        sample_comparison_no_change.head.commit.repository, condition
    )
    assert (
        HasEnoughRequiredChanges.check_condition(notifier, sample_comparison_no_change)
        == expected
    )


@pytest.mark.parametrize(
    "affected_lines, expected",
    [
        pytest.param(["4", "8", "4", "8"], False, id="patch_100%_covered"),
        pytest.param(["1", "8", "1", "8"], True, id="patch_NOT_100%_covered"),
    ],
)
def test_uncovered_patch(
    sample_comparison_no_change, mock_repo_provider, affected_lines, expected
):
    mock_repo_provider.get_compare.return_value = _get_mock_compare_result(
        "file_1.go", affected_lines
    )
    notifier = _get_notifier(
        sample_comparison_no_change.head.commit.repository,
        [CoverageCommentRequiredChanges.uncovered_patch.value],
    )
    assert (
        HasEnoughRequiredChanges.check_condition(notifier, sample_comparison_no_change)
        == expected
    )


@pytest.mark.parametrize(
    "comparison_name, yaml, expected",
    [
        pytest.param("sample_comparison", {}, False, id="positive_change"),
        pytest.param(
            "sample_comparison_negative_change",
            {},
            True,
            id="negative_change_no_extra_config",
        ),
        pytest.param(
            "sample_comparison_negative_change",
            {"coverage": {"status": {"project": True}}},
            True,
            id="negative_change_bool_config",
        ),
        pytest.param(
            "sample_comparison_negative_change",
            {"coverage": {"status": {"project": {"threshold": 10}}}},
            False,
            id="negative_change_high_threshold",
        ),
    ],
)
def test_coverage_drop_with_different_project_configs(
    comparison_name, yaml, expected, request
):
    comparison: ComparisonProxy = request.getfixturevalue(comparison_name)
    comparison.comparison.current_yaml = UserYaml(yaml)
    notifier = _get_notifier(
        comparison.head.commit.repository,
        [CoverageCommentRequiredChanges.coverage_drop.value],
    )
    assert HasEnoughRequiredChanges.check_condition(notifier, comparison) == expected
