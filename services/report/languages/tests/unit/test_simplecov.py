import pprint
from json import loads
from platform import processor

from services.report.languages import simplecov
from services.report.report_builder import ReportBuilder
from tests.base import BaseTestCase

txt_v17 = """
{
    "timestamp": 1597939304,
    "command_name": "RSpec",
    "files": [
        {
            "filename": "controllers/tests_controller.rb",
            "covered_percent": 27.5,
            "coverage": [
                    1,
                    null,
                    0
            ]
        }
    ]
}
"""

txt_v18 = """
{
    "timestamp": 1597939304,
    "command_name": "RSpec",
    "files": [
        {
            "filename": "controllers/tests_controller.rb",
            "covered_percent": 27.5,
            "coverage": {
                "lines": [
                    1,
                    null,
                    0
                ]
            },
            "covered_strength": 0.275,
            "covered_lines": 11,
            "lines_of_code": 40
        }
    ]
}
"""


class TestSimplecovProcessor(BaseTestCase):
    def test_parse_simplecov(self):
        def fixes(path):
            assert path == "controllers/tests_controller.rb"
            return path

        expected_result_archive = {
            "controllers/tests_controller.rb": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, None, None, [[0, None, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }

        report_builder = ReportBuilder(
            current_yaml={}, sessionid=0, ignored_lines={}, path_fixer=fixes
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = simplecov.from_json(loads(txt_v17), report_builder_session)
        processed_report = self.convert_report_to_better_readable(report)
        pprint.pprint(processed_report["archive"])
        assert expected_result_archive == processed_report["archive"]

        report = simplecov.from_json(loads(txt_v18), report_builder_session)
        processed_report = self.convert_report_to_better_readable(report)
        pprint.pprint(processed_report["archive"])
        assert expected_result_archive == processed_report["archive"]

    def test_process(self):
        def fixes(path):
            assert path == "controllers/tests_controller.rb"
            return path

        expected_result_archive = {
            "controllers/tests_controller.rb": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, None, None, [[0, None, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }

        report_builder = ReportBuilder(
            current_yaml={}, sessionid=0, ignored_lines={}, path_fixer=fixes
        )
        processor = simplecov.SimplecovProcessor()
        report = processor.process("filename", loads(txt_v17), report_builder)
        processed_report = self.convert_report_to_better_readable(report)
        pprint.pprint(processed_report["archive"])
        assert expected_result_archive == processed_report["archive"]
