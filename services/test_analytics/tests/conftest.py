import pytest
from shared.config import get_config
from shared.storage import get_appropriate_storage_service
from shared.storage.exceptions import BucketAlreadyExistsError


@pytest.fixture
def storage(mock_configuration):
    storage_service = get_appropriate_storage_service()
    try:
        storage_service.create_root_storage(get_config("services", "minio", "bucket"))
    except BucketAlreadyExistsError:
        pass
    return storage_service
