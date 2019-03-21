from json import dumps, loads

from tests.base import BaseTestCase
from services.report.languages import xcode


txt = '''/source:
      1|    |line
      2|   1|line
  ------------------
  | -[UVWelcomeViewController dealloc]:
  |      0|  360|        noErr                   OSErr: function performed properly - no error
  ------------------
      3|   0|line

/totally_empty:
/file:
    1|   |line
    2|   1k|line
           warning: The file '/Users/Jack/Documents/Coupgon/sdk-ios/Source/CPGCoupgonsViewController.swift' isn't covered.
    \033[0;36m/file:\033[0m
    3|   1m|line
    4|   1|   }

/ignore:
    1|   0|line
'''

result = {
    "files": {
        "source": {
            "l": {
                "2": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": 0, "s": [[0, 0, None, None, None]]}
            }
        },
        "file": {
            "l": {
                "2": {"c": 1000, "s": [[0, 1000, None, None, None]]},
                "3": {"c": 99999, "s": [[0, 99999, None, None, None]]}
            }
        }
    }
}


class TestXCode2(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore':
                return None
            assert path in ('source', 'file', 'empty', 'totally_empty')
            return path

        report = xcode.from_txt(txt, fixes, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint
        pprint.pprint(processed_report['archive'])
        expected_result_archive = {
            'file': [
                (2, 1000, None, [[0, 1000]], None, None),
                (3, 99999, None, [[0, 99999]], None, None)
            ],
            'source': [
                (2, 1, None, [[0, 1]], None, None),
                (3, 0, None, [[0, 0]], None, None)
            ]
        }

        assert expected_result_archive == processed_report['archive']

    def test_removes_last(self):
        report = xcode.from_txt('''\nnothing\n/file:\n    1 |   1|line\n/totally_empty:''', str, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint
        pprint.pprint(processed_report['archive'])

        assert 'totally_empty' not in processed_report['archive']
        assert 'file' in processed_report['archive']
