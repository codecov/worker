import types
import pathmap
from itertools import permutations
import pytest
from tests.base import BaseTestCase


from services.report import fixpaths


class TestFixpaths(BaseTestCase):
    @pytest.mark.parametrize(
        "toc, path, res",
        [
            (['a', 'b', 'c'], 'a', 'a'),  # direct hit
            (['a/b', 'c/d', 'x/y'], 'c/d', 'c/d'),  # direct hit
            (['a/b', 'c/d', 'x/y'], 'd', 'c/d'),  # path to short by 1
            (['a/b', 'c/d', 'x/y'], 'r/d', None),  # ancestors wrong
            (['a/b', 'c/d', 'x/y'], 'a/c/d', 'c/d'),  # path to long
            (['a/b', 'c/d', 'x/y'], 'a/c/d', 'c/d'),  # path to long by 1
            (['a/b', 'a/b/c/d', 'x/y'], 'c/d', 'a/b/c/d'),  # path to long by 3
            (['a/b', 'a/b/c/d', 'x/y'], 'd', 'a/b/c/d'),  # path to short by 3
            (['a', 'b', 'c'], 'd', None),  # no match
            (['a/1', 'b/1', 'c/1'], 'x/y', None)  # no match
        ])
    def test_fix_file_path(self, toc, path, res):
        for _toc in permutations(toc):
            resolver = pathmap.resolve_by_method(',%s,' % ','.join(_toc))
            assert fixpaths.clean_path(None, bool, resolver, path) == res

    @pytest.mark.parametrize("going_in, going_out", [('hello/../world', 'world'),
          ('../hello', 'hello'),
          ('hello/../world/../welcome/a/b/c', 'welcome/a/b/c')])
    def test_remove_steps(self, going_in, going_out):
        assert fixpaths.clean_path(None, bool, False, going_in, True) == going_out

    @pytest.mark.parametrize("path_matcher, res", [(lambda a: True, 'path'),
          (lambda a: False, None)])
    def test_path_matcher(self, path_matcher, res):
        assert fixpaths.clean_path(None, path_matcher, False, 'path', True) == res

    @pytest.mark.parametrize('f', ['path/dist::src',
          'path/dist/::src/',
          '/path/dist::src/'])
    def test_custom_fixes_pre(self, f):
        assert fixpaths.clean_path(fixpaths.fixpaths_to_func([f]),
                                   str,
                                   None,
                                   '/path/dist/file.js') == 'src/file.js'

    @pytest.mark.parametrize("ignore, fixes, res", [(lambda a: True, lambda a: 'path/new', 'path/new'),
          (lambda a: a != 'path/new', lambda a: 'path/new', None)])
    def test_custom_fixes_post(self, ignore, fixes, res):
        def func(path, prefix):
            return fixes(path)

        assert fixpaths.clean_path(func, ignore, None, 'path') == res

    @pytest.mark.parametrize("toc, result", [('a\\ b', ',a b,'),
          ('./a\\b', ',a/b,'),
          ('./a\n./b', ',a,b,')])
    def test_clean_toc(self, toc, result):
        assert fixpaths.clean_toc(toc) == result

    @pytest.mark.parametrize("value", [None, [], False])
    def test_fixpaths_to_func_none(self, value):
        assert fixpaths.fixpaths_to_func(value) is None

    def test_fixpaths_to_func(self):
        func = fixpaths.fixpaths_to_func(['a/::b/'])
        assert isinstance(func, types.FunctionType)
        assert func('a/b') == 'b/b'
        assert func('ab') == 'ab'
        assert func('c/d') == 'c/d'

    @pytest.mark.parametrize("reg", ['**/e::', '.*/e::'])
    def test_fixpaths_to_func_long(self, reg):
        func = fixpaths.fixpaths_to_func([reg])
        assert isinstance(func, types.FunctionType)
        assert func('a/b/c/d/e/f', False) == 'f'
        assert func('ab', False) == 'ab'
        assert func('c/d', False) == 'c/d'

    def test_fixpaths_to_func_prefix(self):
        func = fixpaths.fixpaths_to_func(['::path'])
        assert isinstance(func, types.FunctionType)
        assert func('a') == 'path/a'
        assert func('a', True) == 'path/a'
        assert func('a', False) == 'a'
