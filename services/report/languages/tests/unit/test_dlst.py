import pytest

from services.report.languages import dlst
from test_utils.base import BaseTestCase

from . import create_report_builder_session

RAW = b"""       |empty
      1|coverage
0000000|missed
this is not line....
source file.d is 77% covered"""


class TestDLST(BaseTestCase):
    @pytest.mark.parametrize("filename", ["src/file.lst", "bad/path.lst", ""])
    def test_report(self, filename):
        def fixer(path):
            if path in ("file.d", "src/file.d"):
                return "src/file.d"

        report_builder_session = create_report_builder_session(
            path_fixer=fixer, filename=filename
        )
        dlst.from_string(RAW, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "src/file.d": [
                (2, 1, None, [[0, 1, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }
        assert expected_result_archive == processed_report["archive"]

    def test_none(self):
        report_builder_session = create_report_builder_session(
            path_fixer=lambda _: False, filename=None
        )
        dlst.from_string(b"   1|test\nignore is 100% covered", report_builder_session)
        report = report_builder_session.output_report()
        assert not report

    def test_matches_content(self):
        content, first_line, name = (
            b"   1|test\nignore is 100% covered",
            "   1|test",
            "name",
        )
        assert dlst.DLSTProcessor().matches_content(content, first_line, name)
