import time
from enum import Enum, auto

import sentry_sdk


class UploadFlow(Enum):
    UPLOAD_TASK_BEGIN = auto()
    PROCESSING_BEGIN = auto()
    INITIAL_PROCESSING_COMPLETE = auto()
    BATCH_PROCESSING_COMPLETE = auto()
    PROCESSING_COMPLETE = auto()
    NOTIFIED = auto()


def _get_milli_timestamp():
    return time.time_ns() // 1000000


class CheckpointLogger:
    def __init__(self, cls):
        self.cls = cls
        self.data = {}

    def _validate_checkpoint(self, checkpoint):
        if checkpoint.__class__ != self.cls:
            raise ValueError(
                f"Checkpoint {checkpoint} not part of flow `{self.cls.__name__}`"
            )

    def _subflow_duration(self, start, end):
        self._validate_checkpoint(start)
        self._validate_checkpoint(end)
        if start not in self.data:
            raise ValueError(
                f"Cannot compute duration; missing start checkpoint {start}"
            )
        elif end not in self.data:
            raise ValueError(f"Cannot compute duration; missing end checkpoint {end}")
        elif end.value <= start.value:
            raise ValueError(
                f"Cannot compute duration; end {end} is not after start {start}"
            )

        return self.data[end] - self.data[start]

    def log(self, checkpoint):
        if checkpoint in self.data:
            raise ValueError(f"Already recorded checkpoint {checkpoint}")
        self._validate_checkpoint(checkpoint)
        self.data[checkpoint] = _get_milli_timestamp()

    def submit_subflow(self, metric, start, end):
        duration = self._subflow_duration(start, end)
        sentry_sdk.set_measurement(metric, duration, "milliseconds")
