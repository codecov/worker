from enum import auto

from helpers.checkpoint_logger import (
    BaseFlow,
    failure_events,
    reliability_counters,
    subflows,
    success_events,
)


@failure_events(
    "TOO_MANY_RETRIES",
    "NOTIF_LOCK_ERROR",
    "NOTIF_NO_VALID_INTEGRATION",
    "NOTIF_GIT_CLIENT_ERROR",
    "NOTIF_GIT_SERVICE_ERROR",
    "NOTIF_TOO_MANY_RETRIES",
    "NOTIF_ERROR_NO_REPORT",
)
@success_events(
    "SKIPPING_NOTIFICATION", "NOTIFIED", "NO_PENDING_JOBS", "NOTIF_STALE_HEAD"
)
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
@reliability_counters
class UploadFlow(BaseFlow):
    UPLOAD_TASK_BEGIN = auto()
    NO_PENDING_JOBS = auto()
    TOO_MANY_RETRIES = auto()
    PROCESSING_BEGIN = auto()
    INITIAL_PROCESSING_COMPLETE = auto()
    BATCH_PROCESSING_COMPLETE = auto()
    PROCESSING_COMPLETE = auto()
    SKIPPING_NOTIFICATION = auto()
    NOTIFIED = auto()
    NOTIF_LOCK_ERROR = auto()
    NOTIF_NO_VALID_INTEGRATION = auto()
    NOTIF_GIT_CLIENT_ERROR = auto()
    NOTIF_GIT_SERVICE_ERROR = auto()
    NOTIF_TOO_MANY_RETRIES = auto()
    NOTIF_STALE_HEAD = auto()
    NOTIF_ERROR_NO_REPORT = auto()
