from json import loads, dumps

from tests.base import TestCase
from app.tasks.reports.languages import v1


txt = '''
{
    "coverage": {
        "source": [null, 1],
        "file": {"1": 1, "2": "1", "3": true, "4": "1/2"},
        "empty": {}
    },
    "messages": {
        "source": {
            "1": "Message"
        }
    }
}

'''

result = {
    "files": {
        "source": {
            "l": {
                "1": {
                    "c": 1,
                    "s": [[0, 1, None, None, None]]
                    # "m": ["Message"]
                }
            }
        },
        "file": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]},
                "2": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": True, "t": "b", "s": [[0, True, None, None, None]]},
                "4": {"c": "1/2", "t": "b", "s": [[0, "1/2", None, None, None]]}
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            assert path in ('source', 'file', 'empty')
            return path

        report = v1.from_json(loads(txt), fixes, {}, 0, {})
        report = self.v3_to_v2(report)
        print dumps(report, indent=4)
        self.validate.report(report)
        assert result == report

    def test_not_list(self):
        assert v1.from_json({'coverage': '<string>'}, str, {}, 0, {}) is None
