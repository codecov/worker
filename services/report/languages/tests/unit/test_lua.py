from services.report.languages import lua
from test_utils.base import BaseTestCase

from . import create_report_builder_session

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

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        lua.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

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

    def test_report_with_line_breaks_in_the_beginning(self):
        content = b"\n".join(
            [
                b"==============================================================================",
                b"socks.lua",
                b"==============================================================================",
                b"",
                b"     914 socks = []",
                b"",
                b"     914 function fact(n)",
                b"     914   if n == 0 then",
                b"     914     return 1",
                b"     914   else",
                b"     914     return 0",
                b"     914   end",
                b"     914 end",
                b"<<<<<< EOF",
            ]
        )
        report_builder_session = create_report_builder_session()
        lua.from_txt(content, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "socks.lua": [
                (2, 914, None, [[0, 914, None, None, None]], None, None),
                (4, 914, None, [[0, 914, None, None, None]], None, None),
                (5, 914, None, [[0, 914, None, None, None]], None, None),
                (6, 914, None, [[0, 914, None, None, None]], None, None),
                (7, 914, None, [[0, 914, None, None, None]], None, None),
                (8, 914, None, [[0, 914, None, None, None]], None, None),
                (9, 914, None, [[0, 914, None, None, None]], None, None),
                (10, 914, None, [[0, 914, None, None, None]], None, None),
            ]
        }

        assert expected_result_archive == processed_report["archive"]

    def test_detect(self):
        processor = lua.LuaProcessor()
        assert processor.matches_content(b"=========", "", "") is True
        assert processor.matches_content(b"=== fefef", "", "") is False
        assert processor.matches_content(b"<xml>", "", "") is False
