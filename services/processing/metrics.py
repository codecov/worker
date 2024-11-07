from shared.metrics import Counter, Histogram

from helpers.metrics import BYTE_SIZE_BUCKETS

LABELS_USAGE = Counter(
    "worker_labels_usage",
    "Number of various real-world `carryforward_mode=labels` usages",
    ["codepath"],
)

# The final serialized `Report` sizes, split into `report_json` and `chunks`.
# As the report is often incrementally updated multiple times, this value can
# be biased towards smaller sizes.
PYREPORT_REPORT_JSON_SIZE = Histogram(
    "worker_tasks_upload_finisher_report_json_size",
    "Size (in bytes) of a report's `report_json`.",
    buckets=BYTE_SIZE_BUCKETS,
)
PYREPORT_CHUNKS_FILE_SIZE = Histogram(
    "worker_tasks_upload_finisher_chunks_file_size",
    "Size (in bytes) of a report's `chunks` file.",
    buckets=BYTE_SIZE_BUCKETS,
)

INTERMEDIATE_REPORT_SIZE = Histogram(
    "worker_intermediate_report_size",
    "Size (in bytes) of a serialized intermediate report. The `type` can be `report_json` or `chunks`.",
    ["type", "compression"],
    buckets=BYTE_SIZE_BUCKETS,
)
