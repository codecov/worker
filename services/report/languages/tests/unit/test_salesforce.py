from services.report.languages.salesforce import SalesforceProcessor
from services.report.report_processor import ReportBuilder
from test_utils.base import BaseTestCase


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
        report_builder = ReportBuilder(
            current_yaml=None,
            sessionid=sessionid,
            ignored_lines={},
            path_fixer=lambda x: x,
        )
        res = processor.process(name, user_input, report_builder)
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
                        None,
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

    def test_salesforce_matcher(self):
        name = "test-result-codecoverage.json"

        file_contents = [
            {
                "id": "01p4T000004n1shQAA",
                "name": "LIFXController",
                "totalLines": 29,
                "lines": {"3": 1, "6": 1, "7": 1, "8": 1, "9": 1, "10": 1},
                "totalCovered": 27,
                "coveredPercent": 93,
            }
        ]
        processor = SalesforceProcessor()

        assert processor.matches_content(file_contents, "[", name) is True

    def test_salesforce_matcher_detailed_file(self):
        name = "test-result-7075400002Mmqrs-codecoverage.json"
        file_contents = [
            [
                {
                    "apexClassOrTriggerName": "LIFXController",
                    "apexClassOrTriggerId": "01p4T000004n1shQAA",
                    "apexTestClassId": "01p4T000004n1siQAA",
                    "apexTestMethodName": "testGetLights",
                    "numLinesCovered": 11,
                    "numLinesUncovered": 18,
                    "percentage": "38%",
                    "coverage": {
                        "coveredLines": [1, 2, 3, 4, 5, 6, 7, 8, 9],
                        "uncoveredLines": [10, 11, 12, 13],
                    },
                },
                {
                    "apexClassOrTriggerName": "LIFXController",
                    "apexClassOrTriggerId": "01p4T000004n1shQAA",
                    "apexTestClassId": "01p4T000004n1siQAA",
                    "apexTestMethodName": "testSetPower",
                    "numLinesCovered": 17,
                    "numLinesUncovered": 12,
                    "percentage": "59%",
                    "coverage": {
                        "coveredLines": [1, 2, 3, 4, 5, 6],
                        "uncoveredLines": [7, 8, 9, 10, 11, 12],
                    },
                },
            ]
        ]
        processor = SalesforceProcessor()

        assert processor.matches_content(file_contents, "[", name) is False

    def test_salesforce_matcher_empty_array(self):
        name = "test-result-codecoverage.json"

        file_contents = []
        processor = SalesforceProcessor()

        assert processor.matches_content(file_contents, "[", name) is False
