from shared.reports.resources import Report

from services.report.languages import gcov
from test_utils.base import BaseTestCase

from . import create_report_builder_session

txt = b"""    -:    0:Source:tmp.c
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

txt_duplicate = b"""        -:    0:Source:/project/rsl/h264/Mp4NaluParser.h
209*:13:
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
4:13:
call    0 returned 100%::
call    1 returned 100%::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
90:13:
call    0 returned 100%::
call    1 returned 100%::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
90:13:
call    0 returned 100%::
call    1 returned 100%::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
7:13:
call    0 returned 100%::
call    1 returned 100%::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
18:13:
call    0 returned 100%::
call    1 returned 100%::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
_ZN3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEEC2Ev::
func
#####:13:
call    0 never executed::
call    1 never executed::
func
730:15:
call    0 returned 100%::
call    1 returned 100%::
730:16:
call    0 returned 100%::
730:17:
94222*:19:
94222*:20:
_ZNK3rsl4h26413Mp4NaluParserINS_8DataViewIKhEEE7IsEmptyEv::
"""


class TestGcov(BaseTestCase):
    def test_report(self):
        report_builder_session = create_report_builder_session(
            filename="temp.c.gcov",
            current_yaml={
                "parsers": {
                    "gcov": {"branch_detection": {"conditional": True, "loop": True}}
                }
            },
        )
        gcov.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"] == {
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

    def test_report_duplicate_lines(self):
        report_builder_session = create_report_builder_session(
            filename="#project#rsl#h264#Mp4NaluParser.h.gcov.reduced",
            current_yaml={
                "parsers": {
                    "gcov": {"branch_detection": {"conditional": True, "loop": True}}
                }
            },
        )
        gcov.from_txt(txt_duplicate, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"] == {
            "project/rsl/h264/Mp4NaluParser.h": [
                (13, 90, "m", [[0, 90, None, None, None]], None, None),
                (15, 730, "m", [[0, 730, None, None, None]], None, None),
                (16, 730, None, [[0, 730, None, None, None]], None, None),
                (17, 730, None, [[0, 730, None, None, None]], None, None),
            ]
        }

    def test_no_cond_branch_report(self):
        report_builder_session = create_report_builder_session(
            current_yaml={
                "parsers": {"gcov": {"branch_detection": {"conditional": False}}}
            },
        )
        gcov.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[0, 1, None, None, None]],
            None,
            None,
        )

    def test_single_line_report(self):
        report_builder_session = create_report_builder_session(
            current_yaml={
                "parsers": {"gcov": {"branch_detection": {"conditional": False}}}
            },
        )
        gcov.from_txt(b"        -:    0:Source:another_tmp.c", report_builder_session)
        report = report_builder_session.output_report()

        assert not report
        assert isinstance(report, Report)

    def test_no_cond_loop_report(self):
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"gcov": {"branch_detection": {"loop": False}}}},
        )
        gcov.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[0, 1, None, None, None]],
            None,
            None,
        )
        assert processed_report["archive"]["tmp.c"][6] == (
            14,
            1,
            "b",
            [[0, 1, None, None, None]],
            None,
            None,
        )

    def test_track_macro_report(self):
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"gcov": {"branch_detection": {"macro": True}}}},
        )
        gcov.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[0, 1, None, None, None]],
            None,
            None,
        )
        assert processed_report["archive"]["tmp.c"][5] == (
            13,
            "0/2",
            None,
            [[0, "0/2", None, None, None]],
            None,
            None,
        )

    def test_no_yaml(self):
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"gcov": {}}},
        )
        gcov.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"]["tmp.c"][3] == (
            10,
            1,
            "b",
            [[0, 1, None, None, None]],
            None,
            None,
        )
        assert processed_report["archive"]["tmp.c"][5] == (
            13,
            1,
            None,
            [[0, 1, None, None, None]],
            None,
            None,
        )

    def test_detect(self):
        processor = gcov.GcovProcessor()
        assert processor.matches_content(b"   -: 0:Source:black", "", "") is True
        assert processor.matches_content(b"..... 0:Source:white", "", "") is True
        assert processor.matches_content(b"", "", "") is False
        assert processor.matches_content(b"0:Source", "", "") is False

    def test_ignored(self):
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"gcov": {}}},
            path_fixer=lambda _: None,
        )
        gcov.from_txt(b"   -: 0:Source:black\n", report_builder_session)
        report = report_builder_session.output_report()

        assert not report
