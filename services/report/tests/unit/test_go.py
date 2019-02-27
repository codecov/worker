from tests.base import TestCase
from app.tasks.reports.languages import go


txt = '''mode: atomic
source:1.1,1.10 1 1
source:7.14,9.10 1 1
source:11.26,13.2 1 1
ignore:15.19,17.2 1 1
ignore:
source:15.19,17.2 1 0

source:15.19,17.2 1 1
'''

result = {
    "files": {
        "source": {
            "l": {
                "1": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                    # "p": [[1, 10, 1]]
                },
                "7": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                    # "p": [[14, None, 1]]
                },
                "8": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                },
                "9": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                    # "p": [[None, 10, 1]]
                },
                "11": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                    # "p": [[26, None, 1]]
                },
                "12": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                },
                "15": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                    # "p": [[19, None, 1]]
                },
                "16": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                }
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            return None if 'ignore' in path else path

        report = go.from_txt(txt, fixes, {}, 0, {})
        report = self.v3_to_v2(report)
        self.validate.report(report)
        assert result == report
