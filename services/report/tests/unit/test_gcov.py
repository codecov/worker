from json import dumps

from tests.base import TestCase
from app.tasks.reports.languages import gcov


txt = '''    -:    0:Source:tmp.c
    -:    1:not covered source
    1:    2:hit source
#####:    3:missed source
unconditional  0 never executed
:

    0:    4:ignored /* LCOV_EXCL_START */
    1:    5:ignored
    0:    6:ignored /* LCOV_EXCL_END */
    0:    7:ignored LCOV_EXCL_LINE
=====:    8:sytax error
#####:    9:}
branch  0 never executed
branch  1 never executed
    1:   10:    if ( )
branch  0 taken 221 (fallthrough)
branch  1 taken 3
branch  2 never executed
branch  3 taken 0
function -[RGPropertyDeclaration .cxx_destruct] called 0 returned 0% blocks executed 0%
    1:   11:method
#####:    10:inline
#####:    11:static
#####:    12:} // hello world
    1:    13: MACRO_METHOD('blah');
branch  0 never executed
branch  1 never executed
    1:    14: for (x)
branch  0 taken 3
branch  1 taken 3
    1:   15:  }
    1:   16:@implementation blah;
'''

result = {
    "files": {
        "tmp.c": {
            "l": {
                "2": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                },
                "3": {
                    "c": 0,
                    "s": [[0, 0, None, None, None]]
                },
                "8": {
                    "c": 0,
                    "s": [[0, 0, None, None, None]]
                },
                "10": {
                    "c": "2/4",
                    "t": "b",
                    "s": [[0, "2/4", None, None, None]]
                },
                "11": {
                    "c": 1,
                    "t": "m",
                    "s": [[0, 1, None, None, None]]
                },
                "13": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                },
                "14": {
                    "c": "2/2",
                    "s": [[0, "2/2", None, None, None]],
                    "t": "b"
                }
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        report = gcov.from_txt('temp.c.gcov', txt, str, {}, 0, {'branch_detection': {'conditional': True, 'loop': True}})
        report = self.v3_to_v2(report)
        self.validate.report(report)
        print dumps(report, indent=4)
        assert report == result

    def test_no_cond_branch_report(self):
        report = gcov.from_txt('', txt, str, {}, 1, {'branch_detection': {'conditional': False}})
        report = self.v3_to_v2(report)
        self.validate.report(report)
        assert report['files']['tmp.c']['l']['10']['c'] == 1

    def test_no_cond_loop_report(self):
        report = gcov.from_txt('', txt, str, {}, 1, {'branch_detection': {'loop': False}})
        report = self.v3_to_v2(report)
        self.validate.report(report)
        assert report['files']['tmp.c']['l']['14']['c'] == 1

    def test_track_macro_report(self):
        report = gcov.from_txt('', txt, str, {}, 1, {'branch_detection': {'macro': True}})
        report = self.v3_to_v2(report)
        self.validate.report(report)
        assert report['files']['tmp.c']['l']['13']['c'] == '0/2'
        assert report['files']['tmp.c']['l']['13'].get('t') is None

    def test_detect(self):
        assert gcov.detect('   -: 0:Source:black') is True
        assert gcov.detect('..... 0:Source:white') is True
        assert gcov.detect('') is False
        assert gcov.detect('0:Source') is False

    def test_ignored(self):
        assert gcov.from_txt('', '   -: 0:Source:black\n', lambda a: None, {}, 0, {}) is None
