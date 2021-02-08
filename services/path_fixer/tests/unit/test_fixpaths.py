import pytest
from tests.base import BaseTestCase


from services.path_fixer import fixpaths


paths = [
    ("a\\ b", ["a b"]),
    ("./a\\b", ["a/b"]),
    ("./a\n./b", ["a", "b"]),
    ("path/target/delombok/a\n./b", ["b"]),
    ("comma,txt\nb", ["comma,txt", "b"]),
    ('a\n"\\360\\237\\215\\255.txt"\nb', ["a", "🍭.txt", "b"]),
]


class TestFixpaths(BaseTestCase):
    @pytest.mark.parametrize("toc, result", paths)
    def test_clean_toc(self, toc, result):
        assert fixpaths.clean_toc(toc) == result

    def test_unquote_git_path(self):
        assert fixpaths.unquote_git_path("\\360\\237\\215\\255.txt") == "🍭.txt"
