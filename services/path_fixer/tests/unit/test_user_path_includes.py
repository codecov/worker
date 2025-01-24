from services.path_fixer.user_path_includes import UserPathIncludes
from test_utils.base import BaseTestCase


class TestUserPathIncludes(BaseTestCase):
    def test_user_path_fixes_empty(self):
        path_patterns = []
        upi = UserPathIncludes(path_patterns)
        assert upi("sample/path/to/file.go")
        assert upi("any/to/file.cpp")

    def test_user_path_fixes_star(self):
        path_patterns = [".*", "whatever"]
        upi = UserPathIncludes(path_patterns)
        assert upi("sample/path/to/file.go")
        assert upi("any/to/file.cpp")

    def test_user_path_regex(self):
        path_patterns = ["sample/[^/]+/to/.*"]
        upi = UserPathIncludes(path_patterns)
        assert upi("sample/path/to/file.go")
        assert upi("sample/something/to/haha.cpp")
        assert not upi("any/to/file.cpp")

    def test_user_path_no_regex_elements(self):
        path_patterns = ["normal/sample/path/file.py"]
        upi = UserPathIncludes(path_patterns)
        assert upi("normal/sample/path/file.py")
        assert upi("normal/sample/path/file.pyc")
        assert not upi("any/to/file.cpp")
