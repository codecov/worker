from json import loads

from services.report.languages import coveralls
from services.report.report_builder import ReportBuilder
from test_utils.base import BaseTestCase

txt = """
{
    "source_files": [
    {
      "name": "file",
      "coverage": [0, 1, null]
    },
    {
      "name": "ignore",
      "coverage": [null, 1, 0]
    }
    ]
}
"""


class TestCoveralls(BaseTestCase):
    def test_detect(self):
        assert coveralls.detect({"source_files": ""})
        assert not coveralls.detect({"coverage": ""})

    def test_report(self):
        def fixes(path):
            assert path in ("file", "ignore")
            return path if path == "file" else None

        report_builder = ReportBuilder(
            path_fixer=fixes, ignored_lines={}, sessionid=0, current_yaml=None
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = coveralls.from_json(loads(txt), report_builder_session)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report)
        expected_result = {
            "archive": {
                "file": [
                    (1, 0, None, [[0, 0, None, None, None]], None, None),
                    (2, 1, None, [[0, 1, None, None, None]], None, None),
                ]
            },
            "report": {
                "files": {
                    "file": [
                        0,
                        [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                        None,
                    ]
                },
                "sessions": {},
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 0,
                "c": "50.00000",
                "d": 0,
                "diff": None,
                "f": 1,
                "h": 1,
                "m": 1,
                "n": 2,
                "p": 0,
                "s": 0,
            },
        }

        assert processed_report == expected_result
