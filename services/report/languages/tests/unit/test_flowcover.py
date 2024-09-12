from services.report.languages import flowcover
from test_utils.base import BaseTestCase

from . import create_report_builder_session

json = {
    "files": {
        "file.js": {
            "expressions": {
                "covered_locs": [
                    {"start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 5}}
                ],
                "uncovered_locs": [
                    {"start": {"line": 2, "column": 1}, "end": {"line": 3, "column": 5}}
                ],
            }
        }
    }
}


class TestFlowCover(BaseTestCase):
    def test_report(self):
        report_builder_session = create_report_builder_session()
        flowcover.from_json(json, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "file.js": [
                (1, 1, None, [[0, 1, None, [[1, 5, 1]], None]], None, None),
                (2, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }
        assert expected_result_archive == processed_report["archive"]
