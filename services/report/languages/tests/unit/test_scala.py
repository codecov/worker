from json import dumps

from tests.base import BaseTestCase
from services.report.languages import scala


json = {
    "total": 87,
    "fileReports": [
        {
            "filename": "f1",
            "total": 100,
            "coverage": {
                "34": 1,
                "19": 1,
                "26": 0,
                "16": 0,
                "32": 0,
                "36": 1,
                "25": 1,
                "18": 1,
            },
        },
        {
            "filename": "f2",
            "total": 38,
            "coverage": {"24": 1, "25": 0, "28": 1, "23": 1},
        },
        {
            "filename": "ignore",
            "total": 38,
            "coverage": {"24": 1, "25": 1, "28": 1, "23": 1},
        },
    ],
}


class TestScala(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore":
                return None
            assert path in ("f1", "f2", "ignore")
            return path

        report = scala.from_json(json, fixes, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
        expected_result_archive = {
            "f1": [
                (16, 0, None, [[0, 0, None, None, None]], None, None),
                (18, 1, None, [[0, 1, None, None, None]], None, None),
                (19, 1, None, [[0, 1, None, None, None]], None, None),
                (25, 1, None, [[0, 1, None, None, None]], None, None),
                (26, 0, None, [[0, 0, None, None, None]], None, None),
                (32, 0, None, [[0, 0, None, None, None]], None, None),
                (34, 1, None, [[0, 1, None, None, None]], None, None),
                (36, 1, None, [[0, 1, None, None, None]], None, None),
            ],
            "f2": [
                (23, 1, None, [[0, 1, None, None, None]], None, None),
                (24, 1, None, [[0, 1, None, None, None]], None, None),
                (25, 0, None, [[0, 0, None, None, None]], None, None),
                (28, 1, None, [[0, 1, None, None, None]], None, None),
            ],
        }

        assert expected_result_archive == processed_report["archive"]
