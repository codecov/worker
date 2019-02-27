from json import dumps, loads

from tests.base import TestCase
from app.tasks.reports.languages import xcodeplist


class Test(TestCase):
    def test_report(self):
        report = xcodeplist.from_xml(self.readfile('tests/unittests/tasks/reports/xccoverage.xml'), str, {}, 0)
        archive = report.to_archive()
        expect = self.readfile('tests/unittests/tasks/reports/xcodeplist.txt')
        assert archive == expect
