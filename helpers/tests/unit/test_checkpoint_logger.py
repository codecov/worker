import unittest
from enum import Enum, auto
from unittest.mock import ANY, patch

import pytest
import sentry_sdk

from helpers.checkpoint_logger import (
    CheckpointLogger,
    _get_milli_timestamp,
    failure_events,
    from_kwargs,
    subflows,
    success_events,
)


@failure_events("BRANCH_1_FAIL")
@success_events("BRANCH_1_SUCCESS", "BRANCH_2_SUCCESS")
@subflows(
    ("first_checkpoint", "BEGIN", "CHECKPOINT"),
    ("branch_1_to_finish", "BRANCH_1", "BRANCH_1_SUCCESS"),
    ("total_branch_1_time", "BEGIN", "BRANCH_1_SUCCESS"),
    ("total_branch_1_fail_time", "BEGIN", "BRANCH_1_FAIL"),
)
class DecoratedEnum(Enum):
    BEGIN = auto()
    CHECKPOINT = auto()
    BRANCH_1 = auto()
    BRANCH_1_FAIL = auto()
    BRANCH_1_SUCCESS = auto()
    BRANCH_2 = auto()
    BRANCH_2_SUCCESS = auto()


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

    def test_log_checkpoint_twice_ahrows(self):
        checkpoints = CheckpointLogger(TestEnum1, strict=True)
        checkpoints.log(TestEnum1.A)

        with self.assertRaises(ValueError):
            checkpoints.log(TestEnum1.A)

    def test_log_checkpoint_wrong_enum_throws(self):
        checkpoints = CheckpointLogger(TestEnum1, strict=True)

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
        checkpoints = CheckpointLogger(TestEnum1, strict=True)
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
        checkpoints = CheckpointLogger(TestEnum1, strict=True)
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
        checkpoints = CheckpointLogger(TestEnum1, strict=True)
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

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337])
    def test_log_ignore_repeat(self, mock_timestamp):
        checkpoints = CheckpointLogger(TestEnum1, strict=True)

        checkpoints.log(TestEnum1.A)
        time = checkpoints.data[TestEnum1.A]

        checkpoints.log(TestEnum1.A, ignore_repeat=True)
        assert checkpoints.data[TestEnum1.A] == time

    def test_create_from_kwargs(self):
        good_data = {
            TestEnum1.A: 1337,
            TestEnum1.B: 9001,
        }
        good_kwargs = {
            "checkpoints_TestEnum1": good_data,
        }
        checkpoints = from_kwargs(TestEnum1, good_kwargs, strict=True)
        assert checkpoints.data == good_data

        # Data is from TestEnum2 but we expected TestEnum1
        bad_data = {
            TestEnum2.A: 1337,
            TestEnum2.B: 9001,
        }
        bad_kwargs = {
            "checkpoints_TestEnum1": bad_data,
        }
        with self.assertRaises(ValueError):
            checkpoints = from_kwargs(TestEnum1, bad_kwargs, strict=True)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_log_to_kwargs(self, mock_timestamp):
        kwargs = {}

        checkpoints = CheckpointLogger(TestEnum1)
        checkpoints.log(TestEnum1.A, kwargs=kwargs)
        assert "checkpoints_TestEnum1" in kwargs
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.A] == 1337
        assert TestEnum1.B not in kwargs["checkpoints_TestEnum1"]

        checkpoints.log(TestEnum1.B, kwargs=kwargs)
        assert "checkpoints_TestEnum1" in kwargs
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.A] == 1337
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.B] == 9001

        pass

    @pytest.mark.real_checkpoint_logger
    @patch("sentry_sdk.set_measurement")
    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[9001])
    def test_create_log_oneliner(self, mock_timestamp, mock_sentry):
        kwargs = {
            "checkpoints_TestEnum1": {
                TestEnum1.A: 1337,
            },
        }

        expected_duration = 9001 - 1337

        from_kwargs(TestEnum1, kwargs, strict=True).log(
            TestEnum1.B, kwargs=kwargs
        ).submit_subflow("x", TestEnum1.A, TestEnum1.B)

        mock_sentry.assert_called_with("x", expected_duration, "milliseconds")
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.A] == 1337
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.B] == 9001

    def test_success_failure_decorators(self):
        for val in DecoratedEnum.__members__.values():
            if val in [DecoratedEnum.BRANCH_1_SUCCESS, DecoratedEnum.BRANCH_2_SUCCESS]:
                assert val.is_success()
            else:
                assert not val.is_success()

            if val in [DecoratedEnum.BRANCH_1_FAIL]:
                assert val.is_failure()
            else:
                assert not val.is_failure()

    def test_subflows_decorator(self):
        subflows = DecoratedEnum._subflows()

        # No subflows end at these checkpoints
        assert DecoratedEnum.BEGIN not in subflows
        assert DecoratedEnum.BRANCH_1 not in subflows
        assert DecoratedEnum.BRANCH_2 not in subflows

        # `DecoratedEnum.CHECKPOINT` is not a terminal event, but we explicitly
        # defined a subflow ending there.
        checkpoint_subflows = subflows.get(DecoratedEnum.CHECKPOINT)
        assert checkpoint_subflows is not None
        assert len(checkpoint_subflows) == 1
        assert checkpoint_subflows[0] == ("first_checkpoint", DecoratedEnum.BEGIN)

        # All terminal events should have a subflow defined for them which
        # begins at the flow's first event. `BRANCH_1_FAIL` has had this
        # subflow provided by the user, so we should use the user's name.
        branch_1_fail_subflows = subflows.get(DecoratedEnum.BRANCH_1_FAIL)
        assert branch_1_fail_subflows is not None
        assert len(branch_1_fail_subflows) == 1
        assert branch_1_fail_subflows[0] == (
            "total_branch_1_fail_time",
            DecoratedEnum.BEGIN,
        )

        # All terminal events should have a subflow defined for them which
        # begins at the flow's first event. `BRANCH_1_SUCCESS` has had this
        # subflow provided by the user, so we should use the user's name.
        # Also, `BRANCH_1_SUCCESS` is the end of a second subflow. Ensure that
        # both subflows are present.
        branch_1_success_subflows = subflows.get(DecoratedEnum.BRANCH_1_SUCCESS)
        assert branch_1_success_subflows is not None
        assert len(branch_1_success_subflows) == 2
        assert ("total_branch_1_time", DecoratedEnum.BEGIN) in branch_1_success_subflows
        assert (
            "branch_1_to_finish",
            DecoratedEnum.BRANCH_1,
        ) in branch_1_success_subflows

        # All terminal events should have a subflow defined for them which
        # begins at the flow's first event. `BRANCH_2_SUCCESS` has not had this
        # subflow provided by the user, so we should use the default name.
        branch_2_success_subflows = subflows.get(DecoratedEnum.BRANCH_2_SUCCESS)
        assert branch_2_success_subflows is not None
        assert len(branch_2_success_subflows) == 1
        assert branch_2_success_subflows[0] == (
            "DecoratedEnum_BEGIN_to_BRANCH_2_SUCCESS",
            DecoratedEnum.BEGIN,
        )
