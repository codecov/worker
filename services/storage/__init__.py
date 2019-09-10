from services.storage.minio import MinioStorageService
from services.storage.gcp import GCPStorageService
from services.storage.aws import AWSStorageService
from helpers.config import get_config


def get_appropriate_storage_service():
    chosen_storage = get_config('services', 'chosen_storage', 'minio')
    if chosen_storage == 'gcp':
        gcp_config = get_config('services', 'gcp', default={})
        return GCPStorageService(gcp_config)
    elif chosen_storage == 'aws':
        aws_config = get_config('services', 'aws', default={})
    else:
        minio_config = get_config('services', 'minio', default={})
        return MinioStorageService(minio_config)
