from shared.metrics import Histogram

from helpers.metrics import KiB, MiB

RAW_UPLOAD_SIZE = Histogram(
    "worker_services_report_raw_upload_size",
    "Size (in bytes) of a raw upload (which may contain several raw reports)",
    ["version"],
    buckets=[
        100 * KiB,
        500 * KiB,
        1 * MiB,
        5 * MiB,
        10 * MiB,
        50 * MiB,
        100 * MiB,
        200 * MiB,
        500 * MiB,
        1000 * MiB,
    ],
)

RAW_UPLOAD_RAW_REPORT_COUNT = Histogram(
    "worker_services_report_raw_upload_raw_report_count",
    "Number of raw coverage files contained in a raw upload",
    ["version"],
    # The 0.98 bucket is to stop Prometheus from interpolating values much
    # lower than 1 in its histogram_quantile function.
    buckets=[0.98, 1, 2, 3, 4, 5, 7, 10, 30, 50, 100],
)
