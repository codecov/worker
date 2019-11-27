import os

from helpers.environment import get_current_env, Environment


class TestEnvironment(object):

    def test_get_current_env(self):
        assert get_current_env() == Environment.production

    def test_get_current_env_local(sel, mocker):
        mocker.patch.dict(os.environ, {'CURRENT_ENVIRONMENT': 'local'})
        assert get_current_env() == Environment.local
