import functools
import itertools
import logging
import time
from enum import Enum, auto

import sentry_sdk
from shared.metrics import metrics

logger = logging.getLogger(__name__)


def failure_events(*args):
    """
    Class decorator that designates some events as terminal failure conditions.

    @failure_events('ERROR')
    class MyEnum(str, Enum):
        BEGIN: auto()
        CHECKPOINT: auto()
        ERROR: auto()
        FINISHED: auto()
    assert MyEnum.ERROR.is_failure()
    """

    def class_decorator(klass):
        def _failure_events():
            return {v for k, v in klass.__members__.items() if k in args}

        def is_failure(obj):
            return obj in klass._failure_events()

        # `_failure_events` is a cached function rather than a data member so
        # that it is not processed as if it's a value from the enum.
        klass._failure_events = functools.lru_cache(maxsize=1)(_failure_events)
        klass.is_failure = is_failure

        return klass

    return class_decorator


def success_events(*args):
    """
    Class decorator that designates some events as terminal success conditions.

    @success_events('FINISHED')
    class MyEnum(str, Enum):
        BEGIN: auto()
        CHECKPOINT: auto()
        ERROR: auto()
        FINISHED: auto()
    assert MyEnum.FINISHED.is_success()
    """

    def class_decorator(klass):
        def _success_events():
            return {v for k, v in klass.__members__.items() if k in args}

        def is_success(obj):
            return obj in klass._success_events()

        # `_failure_events` is a cached function rather than a data member so
        # that it is not processed as if it's a value from the enum.
        klass._success_events = functools.lru_cache(maxsize=1)(_success_events)
        klass.is_success = is_success

        return klass

    return class_decorator


def subflows(*args):
    """
    Class decorator that defines a set of interesting subflows which should be
    logged as well as the name each should be logged with.

    @subflows(
        ('first_subflow', 'BEGIN', 'CHECKPOINT_A'),
        ('second_subflow', 'CHECKPOINT_A', 'FINISH')
    )
    class MyEnum(str, Enum):
        BEGIN: auto()
        CHECKPOINT: auto()
        ERROR: auto()
        FINISHED: auto()

    A subflow from the first event to each terminal event (success and failure) is
    created implicitly with names like 'MyEnum_BEGIN_to_FINISHED'. This name can be
    overridden by defining the subflow explicitly.
    """

    def class_decorator(klass):
        def _subflows():
            # We get our subflows in the form: [(metric, begin, end)]
            # We want them in the form: {end: [(metric, begin)]}
            # The first step of munging is to group by end
            key_on_end = lambda x: x[2]
            sorted_by_end = sorted(args, key=key_on_end)
            grouped_by_end = itertools.groupby(args, key=key_on_end)

            enum_vals = klass.__members__

            subflows = {}
            for end, group in grouped_by_end:
                # grouped_by_end is not a simple dict so we create our own.
                # `begin` and `end` are still strings at this point so we also want to convert
                # them to enum values.
                subflows[enum_vals[end]] = list(
                    ((metric, enum_vals[begin]) for metric, begin, _ in group)
                )

            # The first enum value is the beginning of the flow, no matter what
            # branches it takes. We want to automatically define a subflow from
            # this beginning to each terminal checkpoint (failures/successes)
            # unless the user provided one already.
            flow_begin = next(iter(enum_vals.values()))

            # `klass._failure_events` comes from the `@failure_events` decorator
            if hasattr(klass, "_failure_events"):
                for end in klass._failure_events():
                    flows_ending_here = subflows.setdefault(
                        end, []
                    )  # [(metric, begin)]
                    if not any((x[1] == flow_begin for x in flows_ending_here)):
                        flows_ending_here.append(
                            (
                                f"{klass.__name__}_{flow_begin.name}_to_{end.name}",
                                flow_begin,
                            )
                        )

            # `klass._success_events` comes from the `@success_events` decorator
            if hasattr(klass, "_success_events"):
                for end in klass._success_events():
                    flows_ending_here = subflows.setdefault(
                        end, []
                    )  # [(metric, begin)]
                    if not any((x[1] == flow_begin for x in flows_ending_here)):
                        flows_ending_here.append(
                            (
                                f"{klass.__name__}_{flow_begin.name}_to_{end.name}",
                                flow_begin,
                            )
                        )

            return subflows

        klass._subflows = functools.lru_cache(maxsize=1)(_subflows)
        return klass

    return class_decorator


def _get_milli_timestamp():
    return time.time_ns() // 1000000


def _kwargs_key(cls):
    return f"checkpoints_{cls.__name__}"


def from_kwargs(cls, kwargs, strict=False):
    data = kwargs.get(_kwargs_key(cls), {})

    # Make sure these checkpoints were made with the same flow
    for key in data.keys():
        if key not in iter(cls):
            raise ValueError(f"Checkpoint {key} not part of flow `{cls.__name__}`")

    return CheckpointLogger(cls, data, strict)


class CheckpointLogger:
    """
    CheckpointLogger is a class that tracks latencies/reliabilities for higher-level
    "flows" that don't map well to auto-instrumented tracing. It can be
    reconstructed from its serialized data allowing you to begin a flow on one host
    and log its completion on another (as long as clock drift is marginal).

      # Simple usage
      checkpoints = CheckpointLogger(UploadFlow)
      checkpoints.log(UploadFlow.BEGIN)
      ...
      checkpoints.log(UploadFlow.PROCESSING_BEGIN)
      checkpoints.submit_subflow("time_before_processing", UploadFlow.BEGIN, UploadFlow.PROCESSING_BEGIN)

      # Alternate usage (`kwargs=kwargs` will insert the log directly into `kwargs`)
      from_kwargs(UploadFlow, kwargs).log(UploadFlow.BEGIN, kwargs=kwargs)
      next_task(kwargs)
      ...
      from_kwargs(UploadFlow, kwargs)
          .log(UploadFlow.NOTIFIED)
          .submit_subflow('notification_latency', UploadFlow.BEGIN, UploadFlow.NOTIFIED)
    """

    def __init__(self, cls, data=None, strict=False):
        self.cls = cls
        self.data = data if data else {}
        self.kwargs_key = _kwargs_key(self.cls)
        self.strict = strict

    def _error(self, msg):
        # When a new version of worker rolls out, it will pick up tasks that
        # may have been enqueued by the old worker and be missing checkpoints
        # data. At least for that reason, we want to allow failing softly.
        metrics.incr("worker.checkpoint_logger.error")
        if self.strict:
            raise ValueError(msg)
        else:
            logger.warning(msg)

    def _validate_checkpoint(self, checkpoint):
        if checkpoint.__class__ != self.cls:
            # This error is not ignored when `self.strict==False` because it's definitely
            # a code mistake
            raise ValueError(
                f"Checkpoint {checkpoint} not part of flow `{self.cls.__name__}`"
            )

    def _subflow_duration(self, start, end):
        self._validate_checkpoint(start)
        self._validate_checkpoint(end)
        if start not in self.data:
            return self._error(
                f"Cannot compute duration; missing start checkpoint {start}"
            )
        elif end not in self.data:
            return self._error(f"Cannot compute duration; missing end checkpoint {end}")
        elif end.value <= start.value:
            # This error is not ignored when `self.strict==False` because it's definitely
            # a code mistake
            raise ValueError(
                f"Cannot compute duration; end {end} is not after start {start}"
            )

        return self.data[end] - self.data[start]

    def log(self, checkpoint, ignore_repeat=False, kwargs=None):
        if checkpoint not in self.data:
            self._validate_checkpoint(checkpoint)
            self.data[checkpoint] = _get_milli_timestamp()
        elif not ignore_repeat:
            self._error(f"Already recorded checkpoint {checkpoint}")

        if kwargs is not None:
            kwargs[self.kwargs_key] = self.data

        return self

    def submit_subflow(self, metric, start, end):
        duration = self._subflow_duration(start, end)
        sentry_sdk.set_measurement(metric, duration, "milliseconds")

        return self


@failure_events("FAILED")
@success_events("NOTIFIED")
@subflows(
    ("time_before_processing", "UPLOAD_TASK_BEGIN", "PROCESSING_BEGIN"),
    ("initial_processing_duration", "PROCESSING_BEGIN", "INITIAL_PROCESSING_COMPLETE"),
    (
        "batch_processing_duration",
        "INITIAL_PROCESSING_COMPLETE",
        "BATCH_PROCESSING_COMPLETE",
    ),
    ("total_processing_duration", "PROCESSING_BEGIN", "PROCESSING_COMPLETE"),
    ("notification_latency", "UPLOAD_TASK_BEGIN", "NOTIFIED"),
)
class UploadFlow(str, Enum):
    UPLOAD_TASK_BEGIN = auto()
    PROCESSING_BEGIN = auto()
    INITIAL_PROCESSING_COMPLETE = auto()
    BATCH_PROCESSING_COMPLETE = auto()
    PROCESSING_COMPLETE = auto()
    NOTIFIED = auto()
    FAILED = auto()
