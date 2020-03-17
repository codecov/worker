from tests.base import BaseTestCase
from services.report.languages import dlst
import pytest

RAW = """       |empty
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

        report = dlst.from_string(filename, RAW, fixer, {}, 0)
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
        report = dlst.from_string(
            None, "   1|test\nignore is 100% covered", lambda a: False, {}, 0
        )
        assert None is report
