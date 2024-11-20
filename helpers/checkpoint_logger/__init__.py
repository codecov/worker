"""
`checkpoint_logger` is a module that tracks latencies/reliabilities for higher-level
"flows" that don't map well to auto-instrumented tracing. It serializes its data
between tasks allowing you to begin a flow on one host and log its completion on
another (as long as clock drift is marginal).

See `UploadFlow` for an example of defining a flow. It's recommended that you
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
    UploadFlow.log(UploadFlow.BEGIN)
    ...
    # each function returns the flow so you can chain `log` calls.
    UploadFlow
        .log(UploadFlow.PROCESSING_COMPLETE)
        .log(UploadFlow.SKIPPING_NOTIFICATION)


    # More complicated usage
    # - Loads data from a previous task that was passed in `kwargs`
    # - Logs `UploadFlow.BEGIN` directly into `kwargs` to pass to the next task
    # - Ignores if `UploadFlow.BEGIN` was already logged (i.e. if this is a task retry)
    from_kwargs([UploadFlow], kwargs)
    UploadFlow.log(UploadFlow.BEGIN, kwargs=kwargs, ignore_repeat=True)
    next_task(kwargs)
    ...
    # when using `@failure_events()` and `@subflows()`, an auto-created subflow
    # is automatically submitted because `UploadFlow.TOO_MANY_RETRIES` is an error
    from_kwargs(UploadFlow, kwargs)
        .log(UploadFlow.TOO_MANY_RETRIES)
"""

import functools
import itertools
import logging
import time
from enum import Enum
from typing import (
    Any,
    Callable,
    ClassVar,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    TypeAlias,
    TypeVar,
)

import sentry_sdk

from helpers.checkpoint_logger.prometheus import PROMETHEUS_HANDLER
from helpers.log_context import get_log_context, set_log_context

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="BaseFlow")
TSubflows: TypeAlias = Mapping[T, Iterable[tuple[str, T]]]


def _error(msg, flow, strict=False):
    # When a new version of worker rolls out, it will pick up tasks that
    # may have been enqueued by the old worker and be missing checkpoints
    # data. At least for that reason, we want to allow failing softly.
    PROMETHEUS_HANDLER.log_errors(flow=flow.__name__)
    if strict:
        raise ValueError(msg)
    else:
        logger.warning(msg)


class BaseFlow(str, Enum):
    """
    Base class for a flow. Defines optional functions which are added by the
    @success_events, @failure_events, @subflows, and @reliability_counters
    decorators to (mostly) appease mypy.

    Inherits from `str` so a dictionary of checkpoints data can be serialized
    between worker tasks. It overrides sort order functions so that it follows
    enum declaration order instead of lexicographic order.
    """

    _subflows: Callable[[], TSubflows]
    _success_events: Callable[[], Iterable[T]]
    _failure_events: Callable[[], Iterable[T]]
    is_success: ClassVar[Callable[[T], bool]]
    is_failure: ClassVar[Callable[[T], bool]]
    log_counters: ClassVar[Callable[[T], None]]

    def _generate_next_value_(
        name: str, start: int, count: int, last_values: list[Any]
    ):  # type: ignore[override]
        """
        This powers `enum.auto()`. It sets the value of "MyEnum.A" to "A".
        """
        return name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.__class__._member_names_.index(
                self.name
            ) == self.__class__._member_names_.index(other.name)
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.__class__._member_names_.index(
                self.name
            ) > self.__class__._member_names_.index(other.name)
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self == other or self > other
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return (not self == other) and (not self > other)
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self == other or self < other
        return NotImplemented

    def __hash__(self):
        return hash(self.name)

    @classmethod
    def beginning(cls: type[T]) -> T:
        return next(iter(cls.__members__.values()))

    @classmethod
    def has_begun(cls: type[T]) -> bool:
        return cls.beginning() in cls._data_from_log_context()

    @classmethod
    def has_ended(cls: type[T]) -> bool:
        return cls.final() in cls._data_from_log_context()

    @classmethod
    def final(cls: type[T]) -> T:
        *_, final = iter(cls.__members__.values())
        return final

    def is_beginning(self):
        return self == self.beginning()

    @classmethod
    def _validate_checkpoint(cls: type[T], checkpoint: T) -> None:
        if checkpoint.__class__ != cls:
            # This error is not ignored when `strict==False` because it's definitely
            # a code mistake
            raise ValueError(
                f"Checkpoint {checkpoint} not part of flow `{cls.__name__}`"
            )

    @classmethod
    def _data_from_log_context(cls: type[T]) -> Mapping[T, int]:
        return get_log_context().checkpoints_data.get(_kwargs_key(cls), {})

    @classmethod
    def _save_to_log_context(cls: type[T], data: Mapping[T, int]):
        log_context = get_log_context()
        log_context.checkpoints_data[_kwargs_key(cls)] = data
        set_log_context(log_context)

    @classmethod
    def save_to_kwargs(cls: type[T], kwargs: dict):
        data = cls._data_from_log_context()
        if data:
            kwargs[_kwargs_key(cls)] = data
        return kwargs

    @classmethod
    def log(
        cls: type[T],
        checkpoint: T,
        ignore_repeat: bool = False,
        kwargs: Optional[MutableMapping[str, Any]] = None,
        strict: bool = False,
    ) -> type[T]:
        cls._validate_checkpoint(checkpoint)

        if not cls.has_begun() and not checkpoint.is_beginning():
            _error(
                f"Tried to log checkpoint {checkpoint} before the flow began",
                cls,
                strict=strict,
            )
            return cls

        is_failure = hasattr(checkpoint, "is_failure") and checkpoint.is_failure()
        is_success = hasattr(checkpoint, "is_success") and checkpoint.is_success()
        is_terminal = is_failure or is_success
        if is_terminal and cls.has_ended():
            _error(
                f"Tried to log terminal checkpoint {checkpoint} after the flow ended",
                cls,
                strict=strict,
            )
            return cls

        data = cls._data_from_log_context()
        if checkpoint in data:
            if not ignore_repeat:
                _error(f"Already recorded checkpoint {checkpoint}", cls, strict=strict)
            return cls

        timestamp = _get_milli_timestamp()
        data[checkpoint] = timestamp
        if is_terminal:
            data[cls.final()] = timestamp
        cls._save_to_log_context(data)

        if kwargs is not None:
            cls.save_to_kwargs(kwargs)

        # `cls._subflows()` comes from the `@subflows` decorator
        # If the flow has pre-defined subflows, we can automatically submit
        # any of them that end with the checkpoint we just logged.
        if hasattr(cls, "_subflows"):
            for metric, beginning in cls._subflows().get(checkpoint, []):  # type: ignore[operator]
                cls.submit_subflow(metric, beginning, checkpoint, data=data)

        # `checkpoint.log_counters()` comes from the `@reliability_counters`
        # decorator
        # Increment event, start, finish, success, failure counters
        if hasattr(checkpoint, "log_counters"):
            checkpoint.log_counters()

        return cls

    @classmethod
    def _subflow_duration(
        cls: type[T], start: T, end: T, data: Mapping[T, int], strict=False
    ) -> Optional[int]:
        cls._validate_checkpoint(start)
        cls._validate_checkpoint(end)
        if start not in data:
            _error(
                f"Cannot compute duration; missing start checkpoint {start}",
                cls,
                strict=strict,
            )
            return None
        elif end not in data:
            _error(
                f"Cannot compute duration; missing end checkpoint {end}",
                cls,
                strict=strict,
            )
            return None
        elif end <= start:
            # This error is not ignored when `self.strict==False` because it's definitely
            # a code mistake
            raise ValueError(
                f"Cannot compute duration; end {end} is not after start {start}"
            )

        return data[end] - data[start]

    @classmethod
    def submit_subflow(
        cls: type[T], metric: str, start: T, end: T, data: Mapping[T, int], strict=False
    ) -> type[T]:
        duration = cls._subflow_duration(start, end, data, strict)
        if duration:
            sentry_sdk.set_measurement(metric, duration, "milliseconds")
            duration_in_seconds = duration / 1000
            PROMETHEUS_HANDLER.log_subflow(
                flow=cls.__name__, subflow=metric, duration=duration_in_seconds
            )

        return cls


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
            def key_on_end(x):
                return x[2]

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
        PROMETHEUS_HANDLER.log_checkpoints(flow=klass.__name__, checkpoint=obj.name)

        # If this is the first checkpoint, increment the number of flows we've begun
        if obj == next(iter(klass.__members__.values())):
            PROMETHEUS_HANDLER.log_begun(flow=klass.__name__)
            return

        is_failure = hasattr(obj, "is_failure") and obj.is_failure()
        is_success = hasattr(obj, "is_success") and obj.is_success()
        is_terminal = is_failure or is_success

        if is_failure:
            PROMETHEUS_HANDLER.log_failure(flow=klass.__name__)
        elif is_success:
            PROMETHEUS_HANDLER.log_success(flow=klass.__name__)

        if is_terminal:
            PROMETHEUS_HANDLER.log_total_ended(flow=klass.__name__)

    klass.log_counters = log_counters
    return klass


def _get_milli_timestamp() -> int:
    return time.time_ns() // 1000000


def _kwargs_key(cls: type[T]) -> str:
    return f"checkpoints_{cls.__name__}"


def from_kwargs(
    flows: list[type[T]], kwargs: MutableMapping[str, Any], strict: bool = False
):
    checkpoints_data = {}
    for cls in flows:
        kwargs_key = _kwargs_key(cls)
        data = kwargs.get(kwargs_key, {})

        # kwargs has been deserialized into a Python dictionary, but our enum values
        # are deserialized as simple strings. We need to ensure the strings are all
        # proper enum values as best we can, and then downcast to enum instances.
        checkpoints_data[kwargs_key] = {}
        for checkpoint, timestamp in data.items():
            try:
                checkpoints_data[kwargs_key][cls(checkpoint)] = timestamp
            except ValueError:
                _error(
                    f"Checkpoint {checkpoint} not part of flow `{cls.__name__}`",
                    cls,
                    strict,
                )
                checkpoints_data[kwargs_key] = {}
                break

    log_context = get_log_context()
    log_context.checkpoints_data = checkpoints_data
    set_log_context(log_context)
