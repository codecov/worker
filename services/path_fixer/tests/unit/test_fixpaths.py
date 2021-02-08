import pytest
from tests.base import BaseTestCase


from services.path_fixer import fixpaths


paths = [
    ("a\\ b", ["a b"]),
    ("./a\\b", ["a/b"]),
    ("./a\n./b", ["a", "b"]),
    ("path/target/delombok/a\n./b", ["b"]),
    ("comma,txt\nb", ["comma,txt", "b"]),
]


class TestFixpaths(BaseTestCase):
    @pytest.mark.parametrize("toc, result", paths)
    def test_clean_toc(self, toc, result):
        assert fixpaths.clean_toc(toc) == result
