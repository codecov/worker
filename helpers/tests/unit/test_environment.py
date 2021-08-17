import os
from pathlib import PosixPath

from helpers.environment import Environment, _calculate_current_env


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
