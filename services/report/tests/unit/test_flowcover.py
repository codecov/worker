from tests.base import TestCase
from app.tasks.reports.languages import flowcover


json = {
    "files": {
        "file.js": {
            "expressions": {
                "covered_locs": [
                    {
                        "start": {
                            "line": 1,
                            "column": 1
                        },
                        "end": {
                            "line": 1,
                            "column": 5
                        }
                    }
                ],
                "uncovered_locs": [
                    {
                        "start": {
                            "line": 2,
                            "column": 1
                        },
                        "end": {
                            "line": 3,
                            "column": 5
                        }
                    }
                ]
            }
        }
    }
}

result = {
    "files": {
        "file.js": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, [[1, 5, 1]], None]]},
                "2": {"c": 0, "s": [[0, 0, None, None, None]]}
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        report = flowcover.from_json(json, str, {}, 0)
        report = self.v3_to_v2(report)
        print report
        self.validate.report(report)
        assert result == report
