from services.report.languages import gap
from test_utils.base import BaseTestCase

from . import create_report_builder_session

RAW = b"""{"Type":"S","File":"lib/error.g","FileId":37}
{"Type":"R","Line":1,"FileId":37}
{"Type":"E","Line":2,"FileId":37}
{"Type":"R","Line":3,"FileId":37}

{"Type":"R","Line":4,"FileId":37}

{"Type":"S","File":"lib/test.g","FileId":1}
{"Type":"R","Line":1,"FileId":1}
"""


class TestGap(BaseTestCase):
    def test_report(self):
        report_builder_session = create_report_builder_session()
        gap.from_string(RAW, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

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
        report_builder_session = create_report_builder_session(filename="aaa")
        gap.GapProcessor().process(data, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {}
        assert expected_result_archive == processed_report["archive"]

    def test_detect(self):
        processor = gap.GapProcessor()
        assert processor.matches_content(b"", "", "") is False
        assert (
            processor.matches_content(
                b"", '{"Type":"S","File":"lib/error.g","FileId":37}', ""
            )
            is True
        )
        assert processor.matches_content(b'{"coverage"}', "", "") is False
        assert processor.matches_content(b"-1.7", "", "") is False
