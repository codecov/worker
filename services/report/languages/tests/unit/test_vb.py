import xml.etree.cElementTree as etree

from services.report.languages import vb
from test_utils.base import BaseTestCase

from . import create_report_builder_session

txt = """<?xml version="1.0" encoding="UTF-8"?>
<results>
  <modules>
    <module name="riosock.dll" path="riosock.dll" id="A8980752D35C194D988F77B70FC7950101000000" block_coverage="59.29" line_coverage="66.67" blocks_covered="166" blocks_not_covered="114" lines_covered="186" lines_partially_covered="4" lines_not_covered="89">
      <functions>
      <function id="7472" name="DefaultLock" type_name="PrioritizedLock" block_coverage="100.00" line_coverage="100.00" blocks_covered="3" blocks_not_covered="0" lines_covered="4" lines_partially_covered="0" lines_not_covered="0">
          <ranges>
            <range source_id="1" covered="yes" start_line="42" start_column="0" end_line="42" end_column="0" />
            <range source_id="1" covered="no" start_line="45" start_column="0" end_line="45" end_column="0" />
          </ranges>
        </function>
        <function id="7552" name="DefaultRelease" type_name="PrioritizedLock" block_coverage="100.00" line_coverage="100.00" blocks_covered="3" blocks_not_covered="0" lines_covered="4" lines_partially_covered="0" lines_not_covered="0">
          <ranges>
            <range source_id="1" covered="yes" start_line="50" start_column="0" end_line="50" end_column="0" />
            <range source_id="1" covered="partial" start_line="52" start_column="0" end_line="52" end_column="0" />
          </ranges>
        </function>
        <function id="8840" token="0x6000008" name="BuildRowForBasicSchema(int)" type_name="RowHelper" block_coverage="100.00" line_coverage="100.00" blocks_covered="5" blocks_not_covered="0" lines_covered="3" lines_partially_covered="0" lines_not_covered="0">
          <ranges>
            <range source_id="0" covered="yes" start_line="90" start_column="9" end_line="90" end_column="10" />
            <range source_id="0" covered="no" start_line="91" start_column="13" end_line="91" end_column="100" />
            <range source_id="0" covered="yes" start_line="92" start_column="9" end_line="92" end_column="10" />
          </ranges>
        </function>
      </functions>
      <source_files>
        <source_file id="0" path="Source\\Mobius\\csharp\\Tests.Common\\RowHelper.cs">
        </source_file>
        <source_file id="1" path="Source\\Mobius\\csharp\\Tests.Common\\Picklers.cs">
        </source_file>
      </source_files>
    </module>
  </modules>
</results>
"""


class TestVBOne(BaseTestCase):
    def test_report(self):
        report_builder_session = create_report_builder_session()
        vb.from_xml(etree.fromstring(txt), report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "Source/Mobius/csharp/Tests.Common/Picklers.cs": [
                (42, 1, None, [[0, 1, None, None, None]], None, None),
                (45, 0, None, [[0, 0, None, None, None]], None, None),
                (50, 1, None, [[0, 1, None, None, None]], None, None),
                (52, True, None, [[0, True, None, None, None]], None, None),
            ],
            "Source/Mobius/csharp/Tests.Common/RowHelper.cs": [
                (90, 1, None, [[0, 1, None, None, None]], None, None),
                (91, 0, None, [[0, 0, None, None, None]], None, None),
                (92, 1, None, [[0, 1, None, None, None]], None, None),
            ],
        }

        assert expected_result_archive == processed_report["archive"]
