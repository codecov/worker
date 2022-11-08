import os
from pathlib import PosixPath

from shared.config import get_config

from helpers.environment import (
    Environment,
    _calculate_current_env,
    get_external_dependencies_folder,
)


class TestEnvironment(object):
    def test_get_current_env(self):
        assert _calculate_current_env() == Environment.production

    def test_get_current_env_local(sel, mocker):
        mocker.patch.dict(os.environ, {"CURRENT_ENVIRONMENT": "local"})
        assert _calculate_current_env() == Environment.local

    def test_get_current_env_enterprise(sel, mocker):
        mocker.patch.dict(os.environ, {"CURRENT_ENVIRONMENT": "local"})
        mock_path_exists = mocker.patch(
            "helpers.environment.os.path.exists", return_value=True
        )
        mocker.patch(
            "helpers.environment._get_current_folder", return_value="/home/path"
        )
        assert _calculate_current_env() == Environment.enterprise
        mock_path_exists.assert_called_with(PosixPath("/home/path/src/is_enterprise"))

    def test_get_external_dependencies_folder(self, mock_configuration):
        assert get_external_dependencies_folder() == "./external_deps"
        mock_configuration.set_params(
            {"services": {"external_dependencies_folder": "some/folder"}}
        )
        assert get_external_dependencies_folder() == "some/folder"
