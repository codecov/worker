import os

from helpers.version import get_current_version


class TestVersion(object):

    def test_get_current_version(self, mocker):
        mocker.patch.dict(os.environ, {"RELEASE_VERSION": "HAHA"})
        assert get_current_version() == "HAHA"

    def test_get_current_version_no_set_version(self, mocker):
        mocker.patch.dict(os.environ, {"nada": "nada"}, clear=True)
        assert get_current_version() == "NO_VERSION"
