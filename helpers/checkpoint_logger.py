import logging
import time
from enum import Enum, auto

import sentry_sdk
from shared.metrics import metrics

logger = logging.getLogger(__name__)


class UploadFlow(str, Enum):
    UPLOAD_TASK_BEGIN = auto()
    PROCESSING_BEGIN = auto()
    INITIAL_PROCESSING_COMPLETE = auto()
    BATCH_PROCESSING_COMPLETE = auto()
    PROCESSING_COMPLETE = auto()
    NOTIFIED = auto()


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
