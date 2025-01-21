import dataclasses
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import shared.storage
from django.db.models import Model
from shared.api_archive.storage import StorageService
from shared.config import get_config


class CleanupContext:
    threadpool: ThreadPoolExecutor
    storage: StorageService
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
