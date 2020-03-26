from json import loads

from tests.base import BaseTestCase
from services.report.languages import rlang


txt = """
{
    "uploader": "R",
    "files": [
        {
            "name": "source/cov.r",
            "coverage": [null, 1, 0]
        },
        {
            "name": "source/app.r",
            "coverage": [null, 1]
        }
    ]
}
"""


class TestRlang(BaseTestCase):
    def test_report(self):
        def fixes(path):
            assert path in ("source/cov.r", "source/app.r")
            return path

        report = rlang.from_json(loads(txt), fixes, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
        expected_result_archive = {
            "source/app.r": [(1, 1, None, [[0, 1, None, None, None]], None, None)],
            "source/cov.r": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 0, None, [[0, 0, None, None, None]], None, None),
            ],
        }

        assert expected_result_archive == processed_report["archive"]
