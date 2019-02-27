from json import dumps

from tests.base import TestCase
from app.tasks.reports.languages import scala


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
                "18": 1
            }
        },
        {
            "filename": "f2",
            "total": 38,
            "coverage": {
                "24": 1,
                "25": 0,
                "28": 1,
                "23": 1
            }
        },
        {
            "filename": "ignore",
            "total": 38,
            "coverage": {
                "24": 1,
                "25": 1,
                "28": 1,
                "23": 1
            }
        }
    ]
}

result = {
    "files": {
        "f1": {
            "l": {
                "25": {"c": 1, "s": [[0, 1, None, None, None]]},
                "26": {"c": 0, "s": [[0, 0, None, None, None]]},
                "16": {"c": 0, "s": [[0, 0, None, None, None]]},
                "19": {"c": 1, "s": [[0, 1, None, None, None]]},
                "32": {"c": 0, "s": [[0, 0, None, None, None]]},
                "36": {"c": 1, "s": [[0, 1, None, None, None]]},
                "34": {"c": 1, "s": [[0, 1, None, None, None]]},
                "18": {"c": 1, "s": [[0, 1, None, None, None]]}
            }
        },
        "f2": {
            "l": {
                "24": {"c": 1, "s": [[0, 1, None, None, None]]},
                "25": {"c": 0, "s": [[0, 0, None, None, None]]},
                "28": {"c": 1, "s": [[0, 1, None, None, None]]},
                "23": {"c": 1, "s": [[0, 1, None, None, None]]}
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore':
                return None
            assert path in ('f1', 'f2', 'ignore')
            return path

        report = scala.from_json(json, fixes, {}, 0)
        report = self.v3_to_v2(report)
        print(dumps(report, indent=4))
        self.validate.report(report)
        assert result == report
