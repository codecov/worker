import pytest
from shared.storage import get_appropriate_storage_service
from shared.storage.exceptions import BucketAlreadyExistsError


@pytest.fixture
def storage(mock_configuration):
    storage_service = get_appropriate_storage_service()
    try:
        storage_service.create_root_storage("archive")
    except BucketAlreadyExistsError:
        pass
    return storage_service
