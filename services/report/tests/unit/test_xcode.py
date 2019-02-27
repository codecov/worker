from json import dumps, loads

from tests.base import TestCase
from app.tasks.reports.languages import xcode


txt = '''/source:
       |   1|line
      1|   2|line
  ------------------
  | -[UVWelcomeViewController dealloc]:
  |      0|  360|        noErr                   OSErr: function performed properly - no error
  ------------------
      0|   3|line

/totally_empty:
/file:
    |   1|line
  1k|   2|line
         warning: The file '/Users/Jack/Documents/Coupgon/sdk-ios/Source/CPGCoupgonsViewController.swift' isn't covered.
  \033[0;36m/file:\033[0m
  1m|   3|line
   1|   4|   }

/ignore:
    0|   1|line

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


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore':
                return None
            assert path in ('source', 'file', 'empty', 'totally_empty')
            return path

        report = xcode.from_txt(txt, fixes, {}, 0)
        report = self.v3_to_v2(report)
        print dumps(report, indent=4, default=list)
        self.validate.report(report)
        assert result == report

    def test_removes_last(self):
        report = xcode.from_txt('''\nnothing\n/file:\n    1 |   1|line\n/totally_empty:''', str, {}, 0)
        report = self.v3_to_v2(report)
        print dumps(report, indent=4, default=list)
        self.validate.report(report)
        assert 'totally_empty' not in report['files']
        assert 'file' in report['files']
