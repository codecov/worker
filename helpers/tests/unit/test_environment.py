import os
from pathlib import PosixPath

from helpers.environment import (
    Environment,
    _calculate_current_env,
    get_external_dependencies_folder,
)


class TestEnvironment(object):
    def test_get_current_env(self, mocker):
        # CURRENT_ENVIRONMENT is a fallback when RUN_ENV is not supplied
        # have to clear out RUN_ENV to test CURRENT_ENVIRONMENT
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch.dict(os.environ, {"CURRENT_ENVIRONMENT": ""})
        assert _calculate_current_env() == Environment.production

    def test_get_current_env_local(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch.dict(os.environ, {"CURRENT_ENVIRONMENT": "local"})
        assert _calculate_current_env() == Environment.local

    def test_get_current_env_enterprise(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
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

    def test_get_current_env_run_env(self, mocker):
        mocker.patch.dict(os.environ, {"RUN_ENV": "ENTERPRISE"})
        assert _calculate_current_env() == Environment.enterprise
        mocker.patch.dict(os.environ, {"RUN_ENV": "DEV"})
        assert _calculate_current_env() == Environment.local
        mocker.patch.dict(os.environ, {"RUN_ENV": "STAGING"})
        assert _calculate_current_env() == Environment.production
        mocker.patch.dict(os.environ, {"RUN_ENV": "TESTING"})
        assert _calculate_current_env() == Environment.production
        mocker.patch.dict(os.environ, {"RUN_ENV": "PRODUCTION"})
        assert _calculate_current_env() == Environment.production
