import unittest

from services.report import fixes


class Test(unittest.TestCase):
    def test_fixes(self):
        res = fixes.get_fixes_from_raw('\n'.join(('./file.kt:2:/*',
                                                  '',
                                                  'EOF: 188 ./file.kt',
                                                  'file.go:20:  ',
                                                  'file.go:x:',
                                                  'file.go',
                                                  'lcov:10:  // LCOV_EXCL_START',
                                                  'lcov:21:// LCOV_EXCL_STOP',
                                                  'file.go:21:  /* ',
                                                  'file.php:23:',
                                                  'file.go:23:  */ ',
                                                  'file.go:50:  /* ',
                                                  'file.go:52:  */ ',
                                                  'file.php:17:      {')), lambda a: a.replace('./', ''))
        assert res == {
            'file.kt': {
                'eof': 188,
                'lines': set([2])
            },
            'lcov': {
                'lines': set([10, 21] + list(range(11, 21))),
            },
            'file.go': {
                'lines': set([20, 21, 23, 50, 52, 22, 51])
            },
            'file.php': {
                'lines': set([23, 17])
            }
        }

    def test_fixes_multiple(self):
        res = fixes.get_fixes_from_raw('file:1,2,3', str)
        assert res == {'file': {'lines': set([1, 2, 3])}}

    def test_fixes_single(self):
        res = fixes.get_fixes_from_raw('file:1:a', str)
        assert res == {'file': {'lines': set([1])}}

    def test_fixes_lcov(self):
        res = fixes.get_fixes_from_raw('file:1:LCOV_EXCL_START\nfile:5:LCOV_EXCL_STOP', str)
        assert res == {'file': {'lines': set([1, 5, 2, 3, 4])}}

    def test_fixes_comment(self):
        res = fixes.get_fixes_from_raw('file:1:/*\nfile:5:*/', str)
        assert res == {'file': {'lines': set([1, 5, 2, 3, 4])}}
