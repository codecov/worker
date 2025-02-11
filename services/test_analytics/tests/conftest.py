import os
from typing import Any

import pytest
import yaml
from shared.config import _get_config_instance, get_config
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


@pytest.fixture()
def custom_config(tmp_path):
    config_instance = _get_config_instance()
    saved_config = config_instance._params

    file_path = tmp_path / "codecov.yml"
    os.environ["CODECOV_YML"] = str(file_path)

    _conf = config_instance._params or {}

    def set(custom_config: dict[Any, Any]):
        # clear cache
        config_instance._params = None

        # for overwrites
        _conf.update(custom_config)
        file_path.write_text(yaml.dump(_conf))

    yield set

    os.environ.pop("CODECOV_YML")
    config_instance._params = saved_config
