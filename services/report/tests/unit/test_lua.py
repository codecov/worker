from tests.base import TestCase
from app.tasks.reports.languages import lua


txt = '''
==============================================================================
source.lua
==============================================================================
    line
**0 line
  1 line
  0 line
  1 line

==============================================================================
file.lua
==============================================================================
  1 line
    line
  1 line
  0 line
**0 line
    line

==============================================================================
ignore.lua
==============================================================================
**0 line

==============================================================================
empty.lua
==============================================================================
    line

==============================================================================
Summary
==============================================================================

27  29  48.21%  ../src/split.lua
------------------------
27  29  48.21%

'''

result = {
    "files": {
        "file.lua": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": 1, "s": [[0, 1, None, None, None]]},
                "5": {"c": 0, "s": [[0, 0, None, None, None]]},
                "4": {"c": 0, "s": [[0, 0, None, None, None]]}
            }
        },
        "source.lua": {
            "l": {
                "3": {"c": 1, "s": [[0, 1, None, None, None]]},
                "2": {"c": 0, "s": [[0, 0, None, None, None]]},
                "5": {"c": 1, "s": [[0, 1, None, None, None]]},
                "4": {"c": 0, "s": [[0, 0, None, None, None]]}
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore.lua':
                return None
            assert path in ('source.lua', 'empty.lua', 'file.lua')
            return path

        report = lua.from_txt(txt, fixes, {}, 0)
        report = self.v3_to_v2(report)
        self.validate.report(report)
        assert result == report

    def test_detect(self):
        assert lua.detect('=========') is True
        assert lua.detect('=== fefef') is False
        assert lua.detect('<xml>') is False
