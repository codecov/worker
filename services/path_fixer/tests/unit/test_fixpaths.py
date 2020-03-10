import pytest
from tests.base import BaseTestCase


from services.path_fixer import fixpaths


class TestFixpaths(BaseTestCase):
    @pytest.mark.parametrize(
        "toc, result", [("a\\ b", ",a b,"), ("./a\\b", ",a/b,"), ("./a\n./b", ",a,b,")]
    )
    def test_clean_toc(self, toc, result):
        assert fixpaths.clean_toc(toc) == result
