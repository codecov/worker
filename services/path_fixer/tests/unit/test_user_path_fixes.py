from services.path_fixer.user_path_fixes import UserPathFixes
from test_utils.base import BaseTestCase


class TestUserPathFixes(BaseTestCase):
    def test_user_path_fixes_empty(self):
        yaml_fixes = []
        upf = UserPathFixes(yaml_fixes)
        assert upf("simple/path.c") == "simple/path.c"

    def test_user_path_fixes_add_prefix_only(self):
        yaml_fixes = ["::added_prefix"]
        upf = UserPathFixes(yaml_fixes)
        assert upf("simple/path.c") == "added_prefix/simple/path.c"
        assert (
            upf("added_prefix/second_path.java")
            == "added_prefix/added_prefix/second_path.java"
        )

    def test_user_path_fixes_remove_prefix_only(self):
        yaml_fixes = ["prefix_to_remove::"]
        upf = UserPathFixes(yaml_fixes)
        assert upf("simple/path.c") == "simple/path.c"
        assert upf("added_prefix/second_path.java") == "added_prefix/second_path.java"
        assert upf("prefix_to_remove/third_path.py") == "third_path.py"
        assert (
            upf("thisisnot/prefix_to_remove/third_path.py")
            == "thisisnot/prefix_to_remove/third_path.py"
        )

    def test_user_path_fixes_remove_add(self):
        yaml_fixes = ["prefix_to_remove::add"]
        upf = UserPathFixes(yaml_fixes)
        assert upf("simple/path.c") == "simple/path.c"
        assert upf("added_prefix/second_path.java") == "added_prefix/second_path.java"
        assert upf("prefix_to_remove/third_path.py") == "add/third_path.py"
        assert (
            upf("thisisnot/prefix_to_remove/third_path.py")
            == "thisisnot/prefix_to_remove/third_path.py"
        )

    def test_user_path_fixes_remove_add_with_regex(self):
        yaml_fixes = [r"(?s:prefix_to_remove/test\-[^\/]+)::add"]
        upf = UserPathFixes(yaml_fixes)
        assert upf("simple/path.c") == "simple/path.c"
        assert upf("added_prefix/second_path.java") == "added_prefix/second_path.java"
        assert upf("prefix_to_remove/test-third_folder/path.py") == "add/path.py"
        assert upf("prefix_to_remove/test-fourth_folder/path.py") == "add/path.py"
        assert upf("prefix_to_remove/test-fourth_oops.py") == "add"
        assert (
            upf("thisisnot/prefix_to_remove/test-third_path.py")
            == "thisisnot/prefix_to_remove/test-third_path.py"
        )
