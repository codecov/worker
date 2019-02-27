from json import dumps, loads
from pathlib import Path
from tests.base import BaseTestCase
from services.report.languages import xcodeplist

here = Path(__file__)
folder = here.parent


class TestXCodePlist(BaseTestCase):

    def readfile(self, filename, if_empty_write=None):
        with open(folder / filename, 'r') as r:
            contents = r.read()

        # codecov: assert not covered start [FUTURE new concept]
        if contents.strip() == '' and if_empty_write:
            with open(folder / filename, 'w+') as r:
                r.write(if_empty_write)
            return if_empty_write
        return contents

    def test_report(self):
        report = xcodeplist.from_xml(self.readfile('xccoverage.xml'), str, {}, 0)
        archive = report.to_archive()
        expect = self.readfile('xcodeplist.txt')
        assert archive == expect
