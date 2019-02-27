from json import dumps
import xml.etree.cElementTree as etree

from tests.base import TestCase
from app.tasks.reports.languages import scoverage


xml = '''<?xml version="1.0" ?>
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
'''

result = {
    "files": {
        "source.scala": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": 0, "s": [[0, 0, None, None, None]]},
                "2": {"c": "0/2", "t": "b", "s": [[0, "0/2", None, None, None]]}
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore':
                return None
            return path

        report = scoverage.from_xml(etree.fromstring(xml), fixes, {}, 0)
        report = self.v3_to_v2(report)
        print(dumps(report, indent=4))
        self.validate.report(report)
        assert result == report
