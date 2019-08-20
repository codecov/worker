from services.storage.minio import MinioStorageService
from helpers.config import get_config


def get_appropriate_storage_service():
    minio_config = get_config('services', 'minio', default={})
    return MinioStorageService(minio_config)
