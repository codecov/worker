from json import loads

from tests.base import TestCase
from app.tasks.reports.languages import rlang


txt = '''
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
'''

result = {
    "files": {
        "source/cov.r": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]},
                "2": {"c": 0, "s": [[0, 0, None, None, None]]}
            }
        },
        "source/app.r": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]}
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            assert path in ('source/cov.r', 'source/app.r')
            return path

        report = rlang.from_json(loads(txt), fixes, {}, 0)
        report = self.v3_to_v2(report)
        self.validate.report(report)
        assert result == report
