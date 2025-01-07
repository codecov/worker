from shared.api_archive.storage import StorageService
from shared.config import get_config


class CleanupContext:
    storage: StorageService
    bucket: str

    def __init__(self):
        self.storage = StorageService()
        self.bucket = get_config("services", "minio", "bucket", default="archive")
