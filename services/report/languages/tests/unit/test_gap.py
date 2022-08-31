from services.report.languages import gap
from services.report.report_processor import ReportBuilder
from tests.base import BaseTestCase

RAW = b"""{"Type":"S","File":"lib/error.g","FileId":37}
{"Type":"R","Line":1,"FileId":37}
{"Type":"E","Line":2,"FileId":37}
{"Type":"R","Line":3,"FileId":37}

{"Type":"R","Line":4,"FileId":37}

{"Type":"S","File":"lib/test.g","FileId":1}
{"Type":"R","Line":1,"FileId":1}
"""

result = {
    "files": {
        "lib/error.g": {
            "l": {
                "1": {"c": 0, "s": [[0, 0, None, None, None]]},
                "2": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": 0, "s": [[0, 0, None, None, None]]},
                "4": {"c": 0, "s": [[0, 0, None, None, None]]},
            }
        },
        "lib/test.g": {"l": {"1": {"c": 0, "s": [[0, 0, None, None, None]]}}},
    }
}


class TestGap(BaseTestCase):
    def test_report(self):
        report = gap.from_string(RAW, str, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        # import pprint
        # pprint.pprint(processed_report['archive'])
        expected_result_archive = {
            "lib/error.g": [
                (1, 0, None, [[0, 0, None, None, None]], None, None),
                (2, 1, None, [[0, 1, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
                (4, 0, None, [[0, 0, None, None, None]], None, None),
            ],
            "lib/test.g": [(1, 0, None, [[0, 0, None, None, None]], None, None)],
        }

        assert expected_result_archive == processed_report["archive"]

    def test_report_from_dict(self):
        data = {"Type": "S", "File": "lib/error.g", "FileId": 37}
        name = "aaa"
        report_builder = ReportBuilder(
            current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
        )
        report = gap.GapProcessor().process(name, data, report_builder)
        processed_report = self.convert_report_to_better_readable(report)
        # import pprint
        # pprint.pprint(processed_report['archive'])
        expected_result_archive = {}

        assert expected_result_archive == processed_report["archive"]

    def test_detect(self):
        assert gap.detect(b"") is False
        assert gap.detect(b'{"Type":"S","File":"lib/error.g","FileId":37}') is True
        assert gap.detect(b'{"coverage"}') is False
        assert gap.detect(b"-1.7") is False
