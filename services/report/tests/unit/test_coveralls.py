from json import loads, dumps

from tests.base import TestCase
from app.tasks.reports.languages import coveralls


txt = '''
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
'''

result = {
    "files": {
        "file": {
            "l": {
                "1": {
                    "c": 0,
                    "s": [[0, 0, None, None, None]]
                },
                "2": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                }
            }
        }
    }
}


class Test(TestCase):
    def test_detect(self):
        assert coveralls.detect({'source_files': ''})
        assert not coveralls.detect({'coverage': ''})

    def test_report(self):
        def fixes(path):
            assert path in ('file', 'ignore')
            return path if path == 'file' else None

        report = coveralls.from_json(loads(txt), fixes, {}, 0)
        report = self.v3_to_v2(report)
        print dumps(report, indent=4)
        self.validate.report(report)
        assert result == report
