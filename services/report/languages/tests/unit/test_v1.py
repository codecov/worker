from json import loads, dumps

from tests.base import BaseTestCase
from services.report.languages import v1


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


class TestVOne(BaseTestCase):
    def test_report(self):
        def fixes(path):
            assert path in ('source', 'file', 'empty')
            return path

        report = v1.from_json(loads(txt), fixes, {}, 0, {})
        processed_report = self.convert_report_to_better_readable(report)
        import pprint
        pprint.pprint(processed_report['archive'])
        expected_result_archive = {
            'file': [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 1, None, [[0, 1, None, None, None]], None, None),
                (3, True, 'b', [[0, True, None, None, None]], None, None),
                (4, '1/2', 'b', [[0, '1/2', None, None, None]], None, None)
            ],
            'source': [
                (1, 1, None, [[0, 1, None, None, None]], None, None)
            ]
        }

        assert expected_result_archive == processed_report['archive']

    def test_not_list(self):
        assert v1.from_json({'coverage': '<string>'}, str, {}, 0, {}) is None
