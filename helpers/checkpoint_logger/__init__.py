import functools
import itertools
import logging
import time
from enum import Enum, auto
from typing import (
    Any,
    Callable,
    ClassVar,
    Generic,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    TypeAlias,
    TypeVar,
)

import sentry_sdk
from shared.metrics import metrics

logger = logging.getLogger(__name__)


T = TypeVar("T", bound="BaseFlow")
TSubflows: TypeAlias = Mapping[T, Iterable[tuple[str, T]]]


class BaseFlow(str, Enum):
    """
    Base class for a flow. Defines optional functions which are added by the
    @success_events, @failure_events, @subflows, and @reliability_counters
    decorators to (mostly) appease mypy.

    Inherits from `str` so a dictionary of checkpoints data can be serialized
    between worker tasks.
    """

    _subflows: Callable[[], TSubflows]
    _success_events: Callable[[], Iterable[T]]
    _failure_events: Callable[[], Iterable[T]]
    is_success: ClassVar[Callable[[T], bool]]
    is_failure: ClassVar[Callable[[T], bool]]
    log_counters: ClassVar[Callable[[T], None]]

    def __new__(cls, value):
        """
        Hook into the creation of each enum member and inject the class name
        into the enum's value (e.g. "MEMBER_NAME" -> "MyEnum.MEMBER_NAME")
        """
        value = f"{cls.__name__}.{value}"
        return super().__new__(cls, value)

    def _generate_next_value_(name, start, count, last_values):
        """
        This powers `enum.auto()`. We want `MyEnum.MEMBER_NAME` as our value but
        we don't have access to the name of `MyEnum` here so just return
        `MEMBER_NAME` for now.
        """
        return name


TClassDecorator: TypeAlias = Callable[[type[T]], type[T]]


def failure_events(*args: str) -> TClassDecorator:
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

    def class_decorator(klass: type[T]) -> type[T]:
        def _failure_events() -> Iterable[T]:
            return {v for k, v in klass.__members__.items() if k in args}

        def is_failure(obj: T) -> bool:
            return obj in _failure_events()

        # `_failure_events` is a cached function rather than a data member so
        # that it is not processed as if it's a value from the enum.
        klass._failure_events = functools.lru_cache(maxsize=1)(_failure_events)
        klass.is_failure = is_failure

        return klass

    return class_decorator


def success_events(*args: str) -> TClassDecorator:
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

    def class_decorator(klass: type[T]) -> type[T]:
        def _success_events() -> Iterable[T]:
            return {v for k, v in klass.__members__.items() if k in args}

        def is_success(obj: T) -> bool:
            return obj in _success_events()

        # `_success_events` is a cached function rather than a data member so
        # that it is not processed as if it's a value from the enum.
        klass._success_events = functools.lru_cache(maxsize=1)(_success_events)
        klass.is_success = is_success

        return klass

    return class_decorator


def subflows(*args: tuple[str, str, str]) -> TClassDecorator:
    """
    Class decorator that defines a set of interesting subflows which should be
    logged as well as the name each should be logged with. It is expected that
    you invoke this **after** @success_events() and/or @failure_events().

    @success_events('FINISH')
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

    def class_decorator(klass: type[T]) -> type[T]:
        def _subflows() -> TSubflows:
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
                # mypy thinks klass._failure_events == klass
                for end in klass._failure_events():  # type: ignore[operator]
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
                # mypy thinks klass._success_events == klass
                for end in klass._success_events():  # type: ignore[operator]
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


def reliability_counters(klass: type[T]) -> type[T]:
    """
    Class decorator that enables computing success/failure rates for a flow. It
    is expected that you invoke this **after** @success_events and/or
    @failure_events.

    @success_events('FINISHED')
    @failure_events('ERROR')
    @reliability_counters
    class MyEnum(str, Enum):
        BEGIN: auto()
        CHECKPOINT: auto()
        ERROR: auto()
        FINISHED: auto()
    MyEnum.BEGIN.log_counters() # increments "MyEnum.begun" counter
    MyEnum.ERROR.log_counters() # increments "MyEnum.failed" counter
    MyEnum.FINISHED.log_counters() # increments "MyEnum.succeeded" counter

    A "MyEnum.ended" counter is incremented for both success and failure events.
    This counter can be compared to "MyEnum.begun" to detect if any branches
    aren't instrumented.
    """

    def log_counters(obj: T) -> None:
        metrics.incr(f"{klass.__name__}.events.{obj.name}")

        # If this is the first checkpoint, increment the number of flows we've begun
        if obj == next(iter(klass.__members__.values())):
            metrics.incr(f"{klass.__name__}.total.begun")
            return

        is_failure = hasattr(obj, "is_failure") and obj.is_failure()
        is_success = hasattr(obj, "is_success") and obj.is_success()
        is_terminal = is_failure or is_success

        if is_failure:
            metrics.incr(f"{klass.__name__}.total.failed")
        elif is_success:
            metrics.incr(f"{klass.__name__}.total.succeeded")

        if is_terminal:
            metrics.incr(f"{klass.__name__}.total.ended")

    klass.log_counters = log_counters
    return klass


def _get_milli_timestamp() -> int:
    return time.time_ns() // 1000000


def _kwargs_key(cls: type[T]) -> str:
    return f"checkpoints_{cls.__name__}"


class CheckpointLogger(Generic[T]):
    """
    CheckpointLogger is a class that tracks latencies/reliabilities for higher-level
    "flows" that don't map well to auto-instrumented tracing. It can be
    reconstructed from its serialized data allowing you to begin a flow on one host
    and log its completion on another (as long as clock drift is marginal).

    See `UploadFlow` for an example of defining a flow. It's recomended that you
    define your flow with the decorators in this file:
    - `@success_events()`, `@failure_events()`: designate some events as terminal
      success/fail states of your flow.
    - `@subflows()`: pre-define subflows that get submitted automatically; implicitly
      define a flow from the first event to each success or failure event
    - `@reliability_counters`: increment event, start, finish, success, failure counters
      for defining reliability metrics for your flow

    It is expected that `@subflows()` and `@reliability_counters` be invoked **after**
    `@success_events()` and/or `@failure_events`.

      # Simple usage
      checkpoints = CheckpointLogger(UploadFlow)
      checkpoints.log(UploadFlow.BEGIN)
      ...
      # each member returns `self` so you can chain `log` and `submit_subflow` calls
      # calling `submit_subflow` manually is unnecessary when using `@subflows()`
      checkpoints
          .log(UploadFlow.PROCESSING_BEGIN)
          .submit_subflow("time_before_processing", UploadFlow.BEGIN, UploadFlow.PROCESSING_BEGIN)

      # More complicated usage
      # - Creates logger from `kwargs`
      # - logs `UploadFlow.BEGIN` directly into `kwargs`
      # - ignores if `UploadFlow.BEGIN` was already logged (i.e. if this is a task retry)
      from_kwargs(UploadFlow, kwargs).log(UploadFlow.BEGIN, kwargs=kwargs, ignore_repeat=True)
      next_task(kwargs)
      ...
      # when using `@failure_events()` and `@subflows()`, an auto-created subflow
      # is automatically submitted because `UploadFlow.TOO_MANY_RETRIES` is an error
      from_kwargs(UploadFlow, kwargs)
          .log(UploadFlow.TOO_MANY_RETRIES)
    """

    _Self = TypeVar("_Self", bound="CheckpointLogger[T]")

    def __init__(
        self: _Self,
        cls: type[T],
        data: Optional[MutableMapping[T, int]] = None,
        strict=False,
    ):
        self.cls = cls
        self.data = data if data else {}
        self.kwargs_key = _kwargs_key(self.cls)
        self.strict = strict

    def _error(self: _Self, msg: str) -> None:
        # When a new version of worker rolls out, it will pick up tasks that
        # may have been enqueued by the old worker and be missing checkpoints
        # data. At least for that reason, we want to allow failing softly.
        metrics.incr("worker.checkpoint_logger.error")
        if self.strict:
            raise ValueError(msg)
        else:
            logger.warning(msg)

    def _validate_checkpoint(self: _Self, checkpoint: T) -> None:
        if checkpoint.__class__ != self.cls:
            # This error is not ignored when `self.strict==False` because it's definitely
            # a code mistake
            raise ValueError(
                f"Checkpoint {checkpoint} not part of flow `{self.cls.__name__}`"
            )

    def _subflow_duration(self: _Self, start: T, end: T) -> Optional[int]:
        self._validate_checkpoint(start)
        self._validate_checkpoint(end)
        if start not in self.data:
            self._error(f"Cannot compute duration; missing start checkpoint {start}")
            return None
        elif end not in self.data:
            self._error(f"Cannot compute duration; missing end checkpoint {end}")
            return None
        elif end.value <= start.value:
            # This error is not ignored when `self.strict==False` because it's definitely
            # a code mistake
            raise ValueError(
                f"Cannot compute duration; end {end} is not after start {start}"
            )

        return self.data[end] - self.data[start]

    def log(
        self: _Self,
        checkpoint: T,
        ignore_repeat: bool = False,
        kwargs: Optional[MutableMapping[str, Any]] = None,
    ) -> _Self:
        if checkpoint not in self.data:
            self._validate_checkpoint(checkpoint)
            self.data[checkpoint] = _get_milli_timestamp()
        elif not ignore_repeat:
            self._error(f"Already recorded checkpoint {checkpoint}")

        if kwargs is not None:
            kwargs[self.kwargs_key] = self.data

        # `self.cls._subflows()` comes from the `@subflows` decorator
        # If the flow has pre-defined subflows, we can automatically submit
        # any of them that end with the checkpoint we just logged.
        if hasattr(self.cls, "_subflows"):
            # mypy thinks selc.cls._subflows == self.cls
            for metric, beginning in self.cls._subflows().get(checkpoint, []):  # type: ignore[operator]
                self.submit_subflow(metric, beginning, checkpoint)

        # `checkpoint.log_counters()` comes from the `@reliability_counters`
        # decorator
        # Increment event, start, finish, success, failure counters
        if hasattr(checkpoint, "log_counters"):
            checkpoint.log_counters()

        return self

    def submit_subflow(self: _Self, metric: str, start: T, end: T) -> _Self:
        duration = self._subflow_duration(start, end)
        if duration:
            sentry_sdk.set_measurement(metric, duration, "milliseconds")

        return self


def from_kwargs(
    cls: type[T], kwargs: MutableMapping[str, Any], strict: bool = False
) -> CheckpointLogger[T]:
    data = kwargs.get(_kwargs_key(cls), {})

    # Make sure these checkpoints were made with the same flow
    for key in data.keys():
        if key not in cls.__members__.values():
            raise ValueError(f"Checkpoint {key} not part of flow `{cls.__name__}`")

    return CheckpointLogger(cls, data, strict)
