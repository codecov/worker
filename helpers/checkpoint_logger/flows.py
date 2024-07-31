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
    "NOTIFIED_ERROR",
    "ERROR_NOTIFYING_ERROR",
)
@success_events(
    "SKIPPING_NOTIFICATION",
    "NOTIFIED",
    "NO_PENDING_JOBS",
    "NOTIF_STALE_HEAD",
    "NO_REPORTS_FOUND",
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
    ("error_notification_latency", "UPLOAD_TASK_BEGIN", "NOTIFIED_ERROR"),
)
@reliability_counters
class UploadFlow(BaseFlow):
    UPLOAD_TASK_BEGIN = auto()
    NO_PENDING_JOBS = auto()
    NO_REPORTS_FOUND = auto()
    TOO_MANY_RETRIES = auto()
    PROCESSING_BEGIN = auto()
    INITIAL_PROCESSING_COMPLETE = auto()
    BATCH_PROCESSING_COMPLETE = auto()
    PROCESSING_COMPLETE = auto()
    SKIPPING_NOTIFICATION = auto()
    NOTIFIED = auto()
    NOTIFIED_ERROR = auto()
    ERROR_NOTIFYING_ERROR = auto()
    NOTIF_LOCK_ERROR = auto()
    NOTIF_NO_VALID_INTEGRATION = auto()
    NOTIF_GIT_CLIENT_ERROR = auto()
    NOTIF_GIT_SERVICE_ERROR = auto()
    NOTIF_TOO_MANY_RETRIES = auto()
    NOTIF_STALE_HEAD = auto()
    NOTIF_ERROR_NO_REPORT = auto()


@failure_events("TEST_RESULTS_ERROR")
@success_events("TEST_RESULTS_NOTIFY")
@subflows(
    ("test_results_notification_latency", "TEST_RESULTS_BEGIN", "TEST_RESULTS_NOTIFY"),
    ("flake_notification_latency", "TEST_RESULTS_BEGIN", "FLAKE_DETECTION_NOTIFY"),
    (
        "test_results_processing_time",
        "TEST_RESULTS_BEGIN",
        "TEST_RESULTS_FINISHER_BEGIN",
    ),
)
@reliability_counters
class TestResultsFlow(BaseFlow):
    TEST_RESULTS_BEGIN = auto()
    TEST_RESULTS_NOTIFY = auto()
    FLAKE_DETECTION_NOTIFY = auto()
    TEST_RESULTS_ERROR = auto()
    TEST_RESULTS_FINISHER_BEGIN = auto()
