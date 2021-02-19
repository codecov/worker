import os

import pytest
from tests.base import BaseTestCase


from services.path_fixer import fixpaths


# Hand-written TOCs.
paths = [
    ("a\\ b", ["a b"]),
    ("./a\\b", ["a/b"]),
    ("./a\n./b", ["a", "b"]),
    ("path/target/delombok/a\n./b", ["b"]),
    ("comma,txt\nb", ["comma,txt", "b"]),
    ('a\n"\\360\\237\\215\\255.txt"\nb', ["a", "🍭.txt", "b"]),
]

# Hand-written filenames.
unquoted_files = {
    "boring.txt": "boring.txt",
    "back\\\\slash.txt": "back\\slash.txt",
    "\\360\\237\\215\\255.txt": "🍭.txt",
}


class TestFixpaths(BaseTestCase):
    @pytest.mark.parametrize("toc, result", paths)
    def test_clean_toc(self, toc, result):
        assert fixpaths.clean_toc(toc) == result

    @pytest.mark.parametrize("path, result", list(unquoted_files.items()))
    def test_unquote_git_path(self, path, result):
        assert fixpaths.unquote_git_path(path) == result

    def test_some_real_git_paths(self):
        prefix = "services/path_fixer/tests/testdir"
        filenames = [
            "café.txt",
            "comma,txt",
            "🍭.txt",
        ]
        joined = [os.path.join(prefix, filename) for filename in filenames]
        toc = """"services/path_fixer/tests/testdir/caf\\303\\251.txt"
services/path_fixer/tests/testdir/comma,txt
"services/path_fixer/tests/testdir/\\360\\237\\215\\255.txt"
"""
        cleaned = fixpaths.clean_toc(toc)
        joined.sort()
        cleaned.sort()
        assert joined == cleaned
