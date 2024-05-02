import xml.etree.cElementTree as etree

from services.report.languages import scoverage
from services.report.report_builder import ReportBuilder
from test_utils.base import BaseTestCase

xml = """<?xml version="1.0" ?>
<statements>
    <statement>
        <source>source.scala</source>
        <line>1</line>
        <branch>false</branch>
        <count>1</count>
    </statement>
    <statement>
        <source>source.scala</source>
        <line>2</line>
        <branch>true</branch>
        <count>0</count>
        <ignored>false</ignored>
    </statement>
    <statement>
        <source>source.scala</source>
        <line>10</line>
        <branch>true</branch>
        <count>0</count>
        <ignored>true</ignored>
    </statement>
    <statement>
        <source>ignore</source>
        <line>1</line>
        <branch>false</branch>
        <count>0</count>
    </statement>
    <statement>
        <source>source.scala</source>
        <line>3</line>
        <branch>false</branch>
        <count>0</count>
    </statement>
    <statement>
        <source>ignore</source>
        <line>1</line>
        <branch>false</branch>
        <count>0</count>
    </statement>
</statements>
"""

result = {
    "files": {
        "source.scala": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": 0, "s": [[0, 0, None, None, None]]},
                "2": {"c": "0/2", "t": "b", "s": [[0, "0/2", None, None, None]]},
            }
        }
    }
}


class TestSCoverage(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore":
                return None
            return path

        report_builder = ReportBuilder(
            path_fixer=fixes, ignored_lines={}, sessionid=0, current_yaml=None
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = scoverage.from_xml(etree.fromstring(xml), report_builder_session)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
        expected_result_archive = {
            "source.scala": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, "0/2", "b", [[0, "0/2", None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }

        assert expected_result_archive == processed_report["archive"]
