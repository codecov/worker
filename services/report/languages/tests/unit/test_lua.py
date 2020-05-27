from tests.base import BaseTestCase
from services.report.languages import lua


txt = b"""
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

"""


class TestLua(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore.lua":
                return None
            assert path in ("source.lua", "empty.lua", "file.lua")
            return path

        report = lua.from_txt(txt, fixes, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
        expected_result_archive = {
            "file.lua": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (3, 1, None, [[0, 1, None, None, None]], None, None),
                (4, 0, None, [[0, 0, None, None, None]], None, None),
                (5, 0, None, [[0, 0, None, None, None]], None, None),
            ],
            "source.lua": [
                (2, 0, None, [[0, 0, None, None, None]], None, None),
                (3, 1, None, [[0, 1, None, None, None]], None, None),
                (4, 0, None, [[0, 0, None, None, None]], None, None),
                (5, 1, None, [[0, 1, None, None, None]], None, None),
            ],
        }

        assert expected_result_archive == processed_report["archive"]

    def test_detect(self):
        assert lua.detect(b"=========") is True
        assert lua.detect(b"=== fefef") is False
        assert lua.detect(b"<xml>") is False
