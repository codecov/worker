import dataclasses
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import shared.storage
from django.db.models import Model
from shared.config import get_config
from shared.storage.base import BaseStorageService


class CleanupContext:
    threadpool: ThreadPoolExecutor
    storage: BaseStorageService
    default_bucket: str
    bundleanalysis_bucket: str

    def __init__(self):
        self.threadpool = ThreadPoolExecutor()
        self.storage = shared.storage.get_appropriate_storage_service()
        self.default_bucket = get_config(
            "services", "minio", "bucket", default="archive"
        )
        self.bundleanalysis_bucket = get_config(
            "bundle_analysis", "bucket_name", default="bundle-analysis"
        )


@contextmanager
def cleanup_context():
    context = CleanupContext()
    try:
        yield context
    finally:
        context.threadpool.shutdown()


@dataclasses.dataclass
class CleanupResult:
    cleaned_models: int
    cleaned_files: int = 0


@dataclasses.dataclass
class CleanupSummary:
    totals: CleanupResult
    summary: dict[type[Model], CleanupResult]

    def add(self, other: "CleanupSummary"):
        self.totals.cleaned_models += other.totals.cleaned_models
        self.totals.cleaned_files += other.totals.cleaned_files

        for model, other_result in other.summary.items():
            if model not in self.summary:
                self.summary[model] = CleanupResult(0)
            result = self.summary[model]

            result.cleaned_models += other_result.cleaned_models
            result.cleaned_files += other_result.cleaned_files
