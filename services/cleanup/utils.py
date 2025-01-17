import dataclasses

import shared.storage
from django.db.models import Model
from shared.api_archive.storage import StorageService
from shared.config import get_config


class CleanupContext:
    storage: StorageService
    default_bucket: str
    bundleanalysis_bucket: str

    def __init__(self):
        self.storage = shared.storage.get_appropriate_storage_service()
        self.default_bucket = get_config(
            "services", "minio", "bucket", default="archive"
        )
        self.bundleanalysis_bucket = get_config(
            "bundle_analysis", "bucket_name", default="bundle-analysis"
        )


@dataclasses.dataclass
class CleanupResult:
    cleaned_models: int
    cleaned_files: int = 0


@dataclasses.dataclass
class CleanupSummary:
    totals: CleanupResult
    summary: dict[type[Model], CleanupResult]
