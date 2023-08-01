import unittest
from enum import Enum, auto
from unittest.mock import ANY, patch

import pytest
import sentry_sdk

from helpers.checkpoint_logger import CheckpointLogger, _get_milli_timestamp


class TestEnum1(Enum):
    A = auto()
    B = auto()
    C = auto()


class TestEnum2(Enum):
    A = auto()
    B = auto()
    C = auto()


class TestCheckpointLogger(unittest.TestCase):
    @patch("time.time_ns", return_value=123456789)
    def test_get_milli_timestamp(self, mocker):
        expected_ms = 123456789 // 1000000
        self.assertEqual(_get_milli_timestamp(), expected_ms)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", return_value=1337)
    def test_log_checkpoint(self, mocker):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)

        self.assertEqual(checkpoints.data[TestEnum1.A], 1337)

    @patch(
        "helpers.checkpoint_logger._get_milli_timestamp",
        side_effect=[1337, 9001, 100000],
    )
    def test_log_multiple_checkpoints(self, mocker):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)
        checkpoints.log(TestEnum1.B)
        checkpoints.log(TestEnum1.C)

        self.assertEqual(checkpoints.data[TestEnum1.A], 1337)
        self.assertEqual(checkpoints.data[TestEnum1.B], 9001)
        self.assertEqual(checkpoints.data[TestEnum1.C], 100000)

    def test_log_checkpoint_twice_throws(self):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)

        with self.assertRaises(ValueError):
            checkpoints.log(TestEnum1.A)

    def test_log_checkpoint_wrong_enum_throws(self):
        checkpoints = CheckpointLogger(TestEnum1)

        with self.assertRaises(ValueError):
            checkpoints.log(TestEnum2.A)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_subflow_duration(self, mocker):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)
        checkpoints.log(TestEnum1.B)

        duration = checkpoints._subflow_duration(TestEnum1.A, TestEnum1.B)
        self.assertEqual(duration, 9001 - 1337)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_subflow_duration_missing_checkpoints(self, mocker):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)
        checkpoints.log(TestEnum1.C)

        # Missing end checkpoint
        with self.assertRaises(ValueError):
            checkpoints._subflow_duration(TestEnum1.A, TestEnum1.B)

        # Missing start checkpoint
        with self.assertRaises(ValueError):
            checkpoints._subflow_duration(TestEnum1.B, TestEnum1.C)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_subflow_duration_wrong_order(self, mocker):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)
        checkpoints.log(TestEnum1.B)

        # End < start
        with self.assertRaises(ValueError):
            checkpoints._subflow_duration(TestEnum1.B, TestEnum1.A)

        # End == start
        with self.assertRaises(ValueError):
            checkpoints._subflow_duration(TestEnum1.A, TestEnum1.A)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", return_value=1337)
    def test_subflow_duration_wrong_enum(self, mocker):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)

        # Wrong enum for start checkpoint
        with self.assertRaises(ValueError):
            checkpoints._subflow_duration(TestEnum2.A, TestEnum1.A)

        # Wrong enum for end checkpoint
        with self.assertRaises(ValueError):
            checkpoints._subflow_duration(TestEnum1.A, TestEnum2.A)

    @pytest.mark.real_checkpoint_logger
    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    @patch("sentry_sdk.set_measurement")
    def test_submit_subflow(self, mock_sentry, mock_timestamp):
        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A)
        checkpoints.log(TestEnum1.B)

        expected_duration = 9001 - 1337
        checkpoints.submit_subflow("metricname", TestEnum1.A, TestEnum1.B)
        mock_sentry.assert_called_with("metricname", expected_duration, "milliseconds")
