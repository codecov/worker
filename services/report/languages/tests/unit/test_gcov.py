from tests.base import BaseTestCase
from services.report.languages import gcov
from covreports.reports.resources import Report

txt = """    -:    0:Source:tmp.c
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
"""


class TestGcov(BaseTestCase):
    def test_report(self):
        report = gcov.from_txt(
            "temp.c.gcov",
            txt,
            str,
            {},
            0,
            {"branch_detection": {"conditional": True, "loop": True}},
        )
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
        expected_result_archive = {
            "tmp.c": [
                (2, 1, None, [[0, 1, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
                (8, 0, None, [[0, 0, None, None, None]], None, None),
                (10, "2/4", "b", [[0, "2/4", None, None, None]], None, None),
                (11, 1, "m", [[0, 1, None, None, None]], None, None),
                (13, 1, None, [[0, 1, None, None, None]], None, None),
                (14, "2/2", "b", [[0, "2/2", None, None, None]], None, None),
            ]
        }

        assert expected_result_archive == processed_report["archive"]

    def test_no_cond_branch_report(self):
        report = gcov.from_txt(
            "", txt, str, {}, 1, {"branch_detection": {"conditional": False}}
        )
        processed_report = self.convert_report_to_better_readable(report)
        assert processed_report["archive"]["tmp.c"][3][0] == 10
        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[1, 1, None, None, None]],
            None,
            None,
        )

    def test_single_line_report(self):
        report = gcov.from_txt(
            "",
            "        -:    0:Source:another_tmp.c",
            str,
            {},
            1,
            {"branch_detection": {"conditional": False}},
        )
        assert not report
        assert isinstance(report, Report)

    def test_no_cond_loop_report(self):
        report = gcov.from_txt(
            "", txt, str, {}, 1, {"branch_detection": {"loop": False}}
        )
        processed_report = self.convert_report_to_better_readable(report)
        assert processed_report["archive"]["tmp.c"][6][0] == 14
        assert processed_report["archive"]["tmp.c"][6] == (
            14,
            1,
            "b",
            [[1, 1, None, None, None]],
            None,
            None,
        )
        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[1, 1, None, None, None]],
            None,
            None,
        )

    def test_track_macro_report(self):
        report = gcov.from_txt(
            "", txt, str, {}, 1, {"branch_detection": {"macro": True}}
        )
        processed_report = self.convert_report_to_better_readable(report)
        assert processed_report["archive"]["tmp.c"][5][0] == 13
        assert processed_report["archive"]["tmp.c"][5] == (
            13,
            "0/2",
            None,
            [[1, "0/2", None, None, None]],
            None,
            None,
        )
        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[1, 1, None, None, None]],
            None,
            None,
        )

    def test_no_yaml(self):
        report = gcov.from_txt("", txt, str, {}, 1, None)
        processed_report = self.convert_report_to_better_readable(report)
        assert processed_report["archive"]["tmp.c"][5][0] == 13
        assert processed_report["archive"]["tmp.c"][5] == (
            13,
            1,
            None,
            [[1, 1, None, None, None]],
            None,
            None,
        )
        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[1, 1, None, None, None]],
            None,
            None,
        )

    def test_detect(self):
        assert gcov.detect("   -: 0:Source:black") is True
        assert gcov.detect("..... 0:Source:white") is True
        assert gcov.detect("") is False
        assert gcov.detect("0:Source") is False

    def test_ignored(self):
        assert (
            gcov.from_txt("", "   -: 0:Source:black\n", lambda a: None, {}, 0, {})
            is None
        )
