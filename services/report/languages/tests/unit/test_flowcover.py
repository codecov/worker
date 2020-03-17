from tests.base import BaseTestCase
from services.report.languages import flowcover


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
        report = flowcover.from_json(json, str, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        # import pprint
        # pprint.pprint(processed_report['archive'])
        expected_result_archive = {
            "file.js": [
                (1, 1, None, [[0, 1, None, [[1, 5, 1]], None]], None, None),
                (2, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }

        assert expected_result_archive == processed_report["archive"]
