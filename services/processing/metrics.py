from shared.metrics import Counter

LABELS_USAGE = Counter(
    "worker_labels_usage",
    "Number of various real-world `carryforward_mode=labels` usages",
    ["codepath"],
)
