from services.report.languages.salesforce import SalesforceProcessor
from tests.base import BaseTestCase


class TestSalesforce(BaseTestCase):
    def test_salesforce_processor_nones(self):
        user_input = [
            None,
            None,
            None,
            {"name": "file.py", "lines": {1: 5}},
            None,
            None,
            None,
            None,
            None,
            None,
        ]
        processor = SalesforceProcessor()
        name = "name"
        sessionid = 0
        res = processor.process(
            name, user_input, lambda x: x, {}, sessionid, repo_yaml=None
        )
        result = self.convert_report_to_better_readable(res)
        assert result == {
            "archive": {
                "file.py": [(1, 5, None, [[0, 5, None, None, None]], None, None)]
            },
            "report": {
                "files": {
                    "file.py": [
                        0,
                        [0, 1, 1, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        [[0, 1, 1, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ]
                },
                "sessions": {},
            },
            "totals": {
                "f": 1,
                "n": 1,
                "h": 1,
                "m": 0,
                "p": 0,
                "c": "100",
                "b": 0,
                "d": 0,
                "M": 0,
                "s": 0,
                "C": 0,
                "N": 0,
                "diff": None,
            },
        }
