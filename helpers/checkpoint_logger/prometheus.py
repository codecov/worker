from shared.metrics import Counter, Histogram

# Main Counter
CHECKPOINTS_TOTAL_BEGUN = Counter(
    "worker_checkpoints_begun",
    "Total number of times a flow's first checkpoint was logged.",
    ["flow"],
)
CHECKPOINTS_TOTAL_SUCCEEDED = Counter(
    "worker_checkpoints_succeeded",
    "Total number of times one of a flow's success checkpoints was logged.",
    ["flow"],
)
CHECKPOINTS_TOTAL_FAILED = Counter(
    "worker_checkpoints_failed",
    "Total number of times one of a flow's failure checkpoints was logged.",
    ["flow"],
)
CHECKPOINTS_TOTAL_ENDED = Counter(
    "worker_checkpoints_ended",
    "Total number of times one of a flow's terminal checkpoints (success or failure) was logged.",
    ["flow"],
)
CHECKPOINTS_ERRORS = Counter(
    "worker_checkpoints_errors",
    "Total number of errors while trying to log checkpoints",
    ["flow"],
)
CHECKPOINTS_EVENTS = Counter(
    "worker_checkpoints_events",
    "Total number of checkpoints logged.",
    ["flow", "checkpoint"],
)
CHECKPOINTS_SUBFLOW_DURATION = Histogram(
    "worker_checkpoints_subflow_duration_seconds",
    "Duration of subflows in seconds.",
    ["flow", "subflow"],
    buckets=[
        0.05,
        0.1,
        0.5,
        1,
        2,
        5,
        10,
        30,
        60,
        120,
        180,
        300,
        600,
        900,
        1200,
        1800,
        2400,
        3600,
    ],
)


class PrometheusCheckpointLoggerHandler:
    """
    PrometheusCheckpointLoggerHandler is a class that is responsible for all
    Prometheus related logs. This checkpoint logic is responsible for logging
    metrics to any checkpoints we define. This class is made with the intent
    of extending different checkpoints for metrics for different needs. The
    methods in this class are mainly used by the CheckpointLogger class.
    """

    def log_begun(self, flow: str):
        CHECKPOINTS_TOTAL_BEGUN.labels(flow=flow).inc()

    def log_failure(self, flow: str):
        CHECKPOINTS_TOTAL_FAILED.labels(flow=flow).inc()

    def log_success(self, flow: str):
        CHECKPOINTS_TOTAL_SUCCEEDED.labels(flow=flow).inc()

    def log_total_ended(self, flow: str):
        CHECKPOINTS_TOTAL_ENDED.labels(flow=flow).inc()

    def log_checkpoints(self, flow: str, checkpoint: str):
        CHECKPOINTS_EVENTS.labels(flow=flow, checkpoint=checkpoint).inc()

    def log_errors(self, flow: str):
        CHECKPOINTS_ERRORS.labels(flow=flow).inc()

    def log_subflow(self, flow: str, subflow: str, duration: int):
        CHECKPOINTS_SUBFLOW_DURATION.labels(flow=flow, subflow=subflow).observe(
            duration
        )


PROMETHEUS_HANDLER = PrometheusCheckpointLoggerHandler()
