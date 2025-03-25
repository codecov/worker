import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from services.comparison import ComparisonProxy
from services.notification.notifiers.base import AbstractBaseNotifier
from services.notification.notifiers.comment.conditions import (
    HasEnoughRequiredChanges,
    NotifyCondition,
)
from shared.validation.types import CoverageCommentRequiredChanges


class TestHasEnoughRequiredChanges(unittest.TestCase):
    def setUp(self):
        self.notifier = MagicMock(spec=AbstractBaseNotifier)
        self.comparison = MagicMock(spec=ComparisonProxy)

    def test_check_coverage_change_with_none_diff(self):
        # Arrange
        self.comparison.get_diff.return_value = None

        # Act
        result = HasEnoughRequiredChanges._check_coverage_change(self.comparison)

        # Assert
        self.assertFalse(result)
        self.comparison.get_diff.assert_called_once()
        self.comparison.head.report.calculate_diff.assert_not_called()

    def test_check_uncovered_patch_with_none_diff(self):
        # Arrange
        self.comparison.get_diff.return_value = None

        # Act
        result = HasEnoughRequiredChanges._check_uncovered_patch(self.comparison)

        # Assert
        self.assertFalse(result)
        self.comparison.get_diff.assert_called_once_with(use_original_base=True)
        self.comparison.head.report.apply_diff.assert_not_called()

    def test_check_any_change_with_none_diff(self):
        # Arrange
        self.comparison.get_diff.return_value = None
        
        # Mock _check_unexpected_changes to return False
        with patch.object(HasEnoughRequiredChanges, '_check_unexpected_changes', return_value=False):
            # Act
            result = HasEnoughRequiredChanges._check_any_change(self.comparison)
            
            # Assert
            self.assertFalse(result)
            self.comparison.get_diff.assert_called_once()