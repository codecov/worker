from tests.base import BaseTestCase
from services.report.languages import go


txt = """mode: atomic
source:1.1,1.10 1 1
source:7.14,9.10 1 1
source:11.26,13.2 1 1
ignore:15.19,17.2 1 1
ignore:
source:15.19,17.2 1 0

source:15.19,17.2 1 1
"""


class TestGo(BaseTestCase):
    def test_report(self):
        def fixes(path):
            return None if "ignore" in path else path

        report = go.from_txt(txt, fixes, {}, 0, {})
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
        expected_result_archive = {
            "source": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (7, 1, None, [[0, 1, None, None, None]], None, None),
                (8, 1, None, [[0, 1, None, None, None]], None, None),
                (9, 1, None, [[0, 1, None, None, None]], None, None),
                (11, 1, None, [[0, 1, None, None, None]], None, None),
                (12, 1, None, [[0, 1, None, None, None]], None, None),
                (15, 1, None, [[0, 1, None, None, None]], None, None),
                (16, 1, None, [[0, 1, None, None, None]], None, None),
            ]
        }

        assert expected_result_archive == processed_report["archive"]
