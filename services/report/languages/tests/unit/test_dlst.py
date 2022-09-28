import pytest

from services.report.languages import dlst
from services.report.report_builder import ReportBuilder
from tests.base import BaseTestCase

RAW = b"""       |empty
      1|coverage
0000000|missed
this is not line....
source file.d is 77% covered"""

result = {
    "files": {
        "src/file.d": {
            "l": {
                "2": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": 0, "s": [[0, 0, None, None, None]]},
            }
        }
    }
}


class TestDLST(BaseTestCase):
    @pytest.mark.parametrize("filename", ["src/file.lst", "bad/path.lst", ""])
    def test_report(self, filename):
        def fixer(path):
            if path in ("file.d", "src/file.d"):
                return "src/file.d"

        report_builder = ReportBuilder(
            path_fixer=fixer, ignored_lines={}, sessionid=0, current_yaml=None
        )
        report_builder_session = report_builder.create_report_builder_session(filename)
        report = dlst.from_string(RAW, report_builder_session)
        processed_report = self.convert_report_to_better_readable(report)
        # import pprint
        # pprint.pprint(processed_report['archive'])
        expected_result_archive = {
            "src/file.d": [
                (2, 1, None, [[0, 1, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }

        assert expected_result_archive == processed_report["archive"]

    def test_none(self):
        report_builder = ReportBuilder(
            path_fixer=lambda a: False, ignored_lines={}, sessionid=0, current_yaml=None
        )
        report_builder_session = report_builder.create_report_builder_session(None)
        report = dlst.from_string(
            b"   1|test\nignore is 100% covered", report_builder_session
        )
        assert None is report

    def test_matches_content(self):
        content, first_line, name = (
            b"   1|test\nignore is 100% covered",
            "   1|test",
            "name",
        )
        return dlst.DLSTProcessor().matches_content(content, first_line, name)
