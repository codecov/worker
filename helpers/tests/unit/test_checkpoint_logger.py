import json
import unittest
from enum import auto
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from helpers.checkpoint_logger import (
    BaseFlow,
    _get_milli_timestamp,
    failure_events,
    from_kwargs,
    reliability_counters,
    subflows,
    success_events,
)
from helpers.log_context import LogContext, set_log_context
from rollouts import CHECKPOINT_ENABLED_REPOSITORIES


class CounterAssertion:
    def __init__(self, metric, labels, expected_value):
        self.metric = metric
        self.labels = labels
        self.expected_value = expected_value

        self.before_value = None
        self.after_value = None

    def __repr__(self):
        return f"<CounterAssertion: {self.metric} {self.labels}>"


class CounterAssertionSet:
    def __init__(self, counter_assertions):
        self.counter_assertions = counter_assertions

    def __enter__(self):
        for assertion in self.counter_assertions:
            assertion.before_value = (
                REGISTRY.get_sample_value(assertion.metric, labels=assertion.labels)
                or 0
            )

    def __exit__(self, exc_type, exc_value, exc_tb):
        for assertion in self.counter_assertions:
            assertion.after_value = (
                REGISTRY.get_sample_value(assertion.metric, labels=assertion.labels)
                or 0
            )
            assert (
                assertion.after_value - assertion.before_value
                == assertion.expected_value
            )


@failure_events("BRANCH_1_FAIL")
@success_events("BRANCH_1_SUCCESS", "BRANCH_2_SUCCESS")
@subflows(
    ("first_checkpoint", "BEGIN", "CHECKPOINT"),
    ("branch_1_to_finish", "BRANCH_1", "BRANCH_1_SUCCESS"),
    ("total_branch_1_time", "BEGIN", "BRANCH_1_SUCCESS"),
    ("total_branch_1_fail_time", "BEGIN", "BRANCH_1_FAIL"),
)
@reliability_counters
class DecoratedEnum(BaseFlow):
    BEGIN = auto()
    CHECKPOINT = auto()
    BRANCH_1 = auto()
    BRANCH_1_FAIL = auto()
    BRANCH_1_SUCCESS = auto()
    BRANCH_2 = auto()
    BRANCH_2_SUCCESS = auto()


class TestEnum1(BaseFlow):
    A = auto()
    B = auto()
    C = auto()


class TestEnum2(BaseFlow):
    D = auto()
    E = auto()
    F = auto()


class SortOrderEnum(BaseFlow):
    C = auto()
    B = auto()
    A = auto()


class TestCheckpointLogger(unittest.TestCase):
    @pytest.fixture(scope="function", autouse=True)
    def inject_mocker(request, mocker):
        request.mocker = mocker

    def setUp(self):
        set_log_context(LogContext())

    @patch("time.time_ns", return_value=123456789)
    def test_get_milli_timestamp(self, mocker):
        expected_ms = 123456789 // 1000000
        self.assertEqual(_get_milli_timestamp(), expected_ms)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", return_value=1337)
    def test_log_checkpoint(self, mocker):
        TestEnum1.log(TestEnum1.A)

        self.assertEqual(TestEnum1._data_from_log_context()[TestEnum1.A], 1337)

    @patch(
        "helpers.checkpoint_logger._get_milli_timestamp",
        side_effect=[1337, 9001, 100000],
    )
    def test_log_multiple_checkpoints(self, mocker):
        TestEnum1.log(TestEnum1.A)
        TestEnum1.log(TestEnum1.B)
        TestEnum1.log(TestEnum1.C)

        data = TestEnum1._data_from_log_context()
        self.assertEqual(data[TestEnum1.A], 1337)
        self.assertEqual(data[TestEnum1.B], 9001)
        self.assertEqual(data[TestEnum1.C], 100000)

    def test_log_checkpoint_twice_throws(self):
        TestEnum1.log(TestEnum1.A)

        with self.assertRaises(ValueError):
            TestEnum1.log(TestEnum1.A, strict=True)

    def test_log_checkpoint_wrong_enum_throws(self) -> None:
        with self.assertRaises(ValueError):
            TestEnum1.log(TestEnum2.D, strict=True)  # type: ignore[arg-type]

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_subflow_duration(self, mocker):
        TestEnum1.log(TestEnum1.A)
        TestEnum1.log(TestEnum1.B)

        data = TestEnum1._data_from_log_context()
        duration = TestEnum1._subflow_duration(TestEnum1.A, TestEnum1.B, data=data)
        self.assertEqual(duration, 9001 - 1337)

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_subflow_duration_missing_checkpoints(self, mocker):
        TestEnum1.log(TestEnum1.A)
        TestEnum1.log(TestEnum1.C)
        data = TestEnum1._data_from_log_context()

        # Missing end checkpoint
        with self.assertRaises(ValueError):
            TestEnum1._subflow_duration(
                TestEnum1.A, TestEnum1.B, data=data, strict=True
            )

        # Missing start checkpoint
        with self.assertRaises(ValueError):
            TestEnum1._subflow_duration(
                TestEnum1.B, TestEnum1.C, data=data, strict=True
            )

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_subflow_duration_wrong_order(self, mocker):
        TestEnum1.log(TestEnum1.A)
        TestEnum1.log(TestEnum1.B)
        data = TestEnum1._data_from_log_context()

        # End < start
        with self.assertRaises(ValueError):
            TestEnum1._subflow_duration(
                TestEnum1.B, TestEnum1.A, data=data, strict=True
            )

        # End == start
        with self.assertRaises(ValueError):
            TestEnum1._subflow_duration(
                TestEnum1.A, TestEnum1.A, data=data, strict=True
            )

    @patch("helpers.checkpoint_logger._get_milli_timestamp", return_value=1337)
    def test_subflow_duration_wrong_enum(self, mocker):
        TestEnum1.log(TestEnum1.A)
        data = TestEnum1._data_from_log_context()

        # Wrong enum for start checkpoint
        with self.assertRaises(ValueError):
            TestEnum1._subflow_duration(
                TestEnum2.D, TestEnum1.A, data=data, strict=True
            )

        # Wrong enum for end checkpoint
        with self.assertRaises(ValueError):
            TestEnum1._subflow_duration(
                TestEnum1.A, TestEnum2.D, data=data, strict=True
            )

    @pytest.mark.real_checkpoint_logger
    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    @patch("sentry_sdk.set_measurement")
    def test_submit_subflow(self, mock_sentry, mock_timestamp):
        TestEnum1.log(TestEnum1.A)
        TestEnum1.log(TestEnum1.B)
        data = TestEnum1._data_from_log_context()

        expected_duration = 9001 - 1337
        TestEnum1.submit_subflow("metricname", TestEnum1.A, TestEnum1.B, data=data)
        mock_sentry.assert_called_with("metricname", expected_duration, "milliseconds")
        assert (
            REGISTRY.get_sample_value(
                "worker_checkpoints_subflow_duration_seconds_sum",
                labels={"flow": "TestEnum1", "subflow": "metricname"},
            )
            == expected_duration / 1000
        )

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337])
    def test_log_ignore_repeat(self, mock_timestamp):
        TestEnum1.log(TestEnum1.A)
        time = TestEnum1._data_from_log_context()[TestEnum1.A]

        TestEnum1.log(TestEnum1.A, ignore_repeat=True)
        assert TestEnum1._data_from_log_context()[TestEnum1.A] == time

    def test_create_from_kwargs(self):
        good_data = {
            TestEnum1.A: 1337,
            TestEnum1.B: 9001,
        }
        deserialized_good_data = json.loads(json.dumps(good_data))
        good_kwargs = {
            "checkpoints_TestEnum1": deserialized_good_data,
        }
        from_kwargs([TestEnum1], good_kwargs, strict=True)
        assert TestEnum1._data_from_log_context() == good_data

        # Data is from TestEnum2 but we expected TestEnum1
        bad_data = {
            TestEnum2.D: 1337,
            TestEnum2.E: 9001,
        }
        deserialized_bad_data = json.loads(json.dumps(bad_data))
        bad_kwargs = {
            "checkpoints_TestEnum1": deserialized_bad_data,
        }
        with self.assertRaises(ValueError):
            checkpoints = from_kwargs([TestEnum1], bad_kwargs, strict=True)

        from_kwargs([TestEnum1], bad_kwargs, strict=False)
        assert TestEnum1._data_from_log_context() == {}

    @patch("helpers.checkpoint_logger._get_milli_timestamp", side_effect=[1337, 9001])
    def test_log_to_kwargs(self, mock_timestamp):
        kwargs = {}

        TestEnum1.log(TestEnum1.A, kwargs=kwargs)
        assert "checkpoints_TestEnum1" in kwargs
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.A] == 1337
        assert TestEnum1.B not in kwargs["checkpoints_TestEnum1"]

        TestEnum1.log(TestEnum1.B, kwargs=kwargs)
        assert "checkpoints_TestEnum1" in kwargs
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.A] == 1337
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.B] == 9001

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

        from_kwargs([TestEnum1], kwargs, strict=True)
        TestEnum1.log(TestEnum1.B, kwargs=kwargs)
        data = TestEnum1._data_from_log_context()
        TestEnum1.submit_subflow("x", TestEnum1.A, TestEnum1.B, data=data)

        mock_sentry.assert_called_with("x", expected_duration, "milliseconds")
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.A] == 1337
        assert kwargs["checkpoints_TestEnum1"][TestEnum1.B] == 9001

    def test_log_before_beginning_throws(self):
        with self.assertRaises(ValueError):
            DecoratedEnum.log(DecoratedEnum.BRANCH_1_SUCCESS, strict=True)

    def test_log_after_end_throws(self):
        DecoratedEnum.log(DecoratedEnum.BEGIN)
        DecoratedEnum.log(DecoratedEnum.BRANCH_1_SUCCESS)

        with self.assertRaises(ValueError):
            DecoratedEnum.log(DecoratedEnum.BRANCH_1_FAIL, strict=True)

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

    @patch.object(CHECKPOINT_ENABLED_REPOSITORIES, "check_value", return_value=123)
    def test_reliability_counters_with_context(self, mock_object):
        repoid = 123
        mock_object.return_value = repoid
        set_log_context(LogContext(repo_id=repoid))

        counter_assertions = [
            CounterAssertion(
                "worker_checkpoints_begun_total", {"flow": "DecoratedEnum"}, 1
            ),
            CounterAssertion(
                "worker_repo_checkpoints_begun_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "BEGIN"},
                1,
            ),
            CounterAssertion(
                "worker_repo_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "BEGIN", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_succeeded_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_succeeded_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_failed_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_failed_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_ended_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_ended_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
        ]
        with CounterAssertionSet(counter_assertions) as a:
            DecoratedEnum.log(DecoratedEnum.BEGIN)

        # Nothing special about `CHECKPOINT` - no counters should change
        counter_assertions = [
            CounterAssertion(
                "worker_checkpoints_begun_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_begun_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "BEGIN"},
                0,
            ),
            CounterAssertion(
                "worker_repo_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "BEGIN", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "CHECKPOINT"},
                1,
            ),
            CounterAssertion(
                "worker_repo_checkpoints_events_total",
                {
                    "flow": "DecoratedEnum",
                    "checkpoint": "CHECKPOINT",
                    "repoid": f"{repoid}",
                },
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_succeeded_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_succeeded_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_failed_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_failed_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_ended_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_reopo_checkpoints_ended_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
        ]
        with CounterAssertionSet(counter_assertions):
            DecoratedEnum.log(DecoratedEnum.CHECKPOINT)

        # Failures should increment both `failed` and `ended`
        counter_assertions = [
            CounterAssertion(
                "worker_checkpoints_begun_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_begun_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_succeeded_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_succeeded_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_failed_total", {"flow": "DecoratedEnum"}, 1
            ),
            CounterAssertion(
                "worker_repo_checkpoints_failed_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_ended_total", {"flow": "DecoratedEnum"}, 1
            ),
            CounterAssertion(
                "worker_repo_checkpoints_ended_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "BRANCH_1_FAIL"},
                1,
            ),
            CounterAssertion(
                "worker_repo_checkpoints_events_total",
                {
                    "flow": "DecoratedEnum",
                    "checkpoint": "BRANCH_1_FAIL",
                    "repoid": f"{repoid}",
                },
                1,
            ),
        ]
        with CounterAssertionSet(counter_assertions):
            DecoratedEnum.log(DecoratedEnum.BRANCH_1_FAIL)

        # Because we've logged a terminal event, we have to restart the flow
        set_log_context(LogContext(repo_id=repoid))
        DecoratedEnum.log(DecoratedEnum.BEGIN)

        # Successes should increment both `succeeded` and `ended`
        counter_assertions = [
            CounterAssertion(
                "worker_checkpoints_begun_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_begun_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_checkpoints_succeeded_total", {"flow": "DecoratedEnum"}, 1
            ),
            CounterAssertion(
                "worker_repo_checkpoints_succeeded_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_failed_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_failed_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_ended_total", {"flow": "DecoratedEnum"}, 1
            ),
            CounterAssertion(
                "worker_repo_checkpoints_ended_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "BRANCH_1_SUCCESS"},
                1,
            ),
            CounterAssertion(
                "worker_repo_checkpoints_events_total",
                {
                    "flow": "DecoratedEnum",
                    "checkpoint": "BRANCH_1_SUCCESS",
                    "repoid": f"{repoid}",
                },
                1,
            ),
        ]
        with CounterAssertionSet(counter_assertions):
            DecoratedEnum.log(DecoratedEnum.BRANCH_1_SUCCESS)

        # Because we've logged a terminal event, we have to restart the flow
        set_log_context(LogContext(repo_id=repoid))
        DecoratedEnum.log(DecoratedEnum.BEGIN)

        # A different success path should also increment `succeeded` and `ended`
        counter_assertions = [
            CounterAssertion(
                "worker_checkpoints_begun_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_begun_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_succeeded_total", {"flow": "DecoratedEnum"}, 1
            ),
            CounterAssertion(
                "worker_repo_checkpoints_succeeded_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_failed_total", {"flow": "DecoratedEnum"}, 0
            ),
            CounterAssertion(
                "worker_repo_checkpoints_failed_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                0,
            ),
            CounterAssertion(
                "worker_checkpoints_ended_total", {"flow": "DecoratedEnum"}, 1
            ),
            CounterAssertion(
                "worker_repo_checkpoints_ended_total",
                {"flow": "DecoratedEnum", "repoid": f"{repoid}"},
                1,
            ),
            CounterAssertion(
                "worker_checkpoints_events_total",
                {"flow": "DecoratedEnum", "checkpoint": "BRANCH_2_SUCCESS"},
                1,
            ),
            CounterAssertion(
                "worker_repo_checkpoints_events_total",
                {
                    "flow": "DecoratedEnum",
                    "checkpoint": "BRANCH_2_SUCCESS",
                    "repoid": f"{repoid}",
                },
                1,
            ),
        ]
        with CounterAssertionSet(counter_assertions):
            DecoratedEnum.log(DecoratedEnum.BRANCH_2_SUCCESS)

    def test_serialize_between_tasks(self):
        """
        BaseFlow must inherit from str in order for our checkpoints dict to be
        readily serializable to JSON for passing between celery tasks.

        We encode the flow name and checkpoint name in the string value so that
        we can validate when we deserialize. Make sure that all works.
        """
        original = {
            TestEnum1.A: 1337,
            TestEnum1.B: 9001,
        }
        serialized = json.dumps(original)
        deserialized = json.loads(serialized)

        assert serialized == '{"A": 1337, "B": 9001}'
        assert deserialized == {
            "A": 1337,
            "B": 9001,
        }

    def test_sort_order(self):
        assert TestEnum1.A == TestEnum1.A
        assert TestEnum1.A < TestEnum1.B
        assert TestEnum1.C > TestEnum1.B
        assert SortOrderEnum.C < SortOrderEnum.B
        assert SortOrderEnum.A > SortOrderEnum.B

        SortOrderEnum.log(SortOrderEnum.C)
        SortOrderEnum.log(SortOrderEnum.B)
        data = SortOrderEnum._data_from_log_context()
        SortOrderEnum._subflow_duration(SortOrderEnum.C, SortOrderEnum.B, data=data)
