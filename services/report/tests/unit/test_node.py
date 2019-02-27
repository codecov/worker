from json import loads, dumps, JSONEncoder
from fractions import Fraction
import pytest
from pathlib import Path
from tests.base import BaseTestCase
from services.report.languages import node


here = Path(__file__)
folder = here.parent

base_report = {
    "ignore": {},
    "empty": {
      "statementMap": {
        "1": {"skip": True}
      },
      "branchMap": {
        "1": {"skip": True}
      },
      "fnMap": {
        "1": {"skip": True}
      }
    }
}


class OwnEncoder(JSONEncoder):

    def default(self, o):
        if isinstance(o, Fraction):
            return str(o)
        return super().default(o)


class Test(BaseTestCase):

    def readjson(self, filename):
        with open(folder / filename, 'r') as d:
            contents = loads(d.read())
            return contents

    def readfile(self, filename, if_empty_write=None):
        with open(folder / filename, 'r') as r:
            contents = r.read()

        # codecov: assert not covered start [FUTURE new concept]
        if contents.strip() == '' and if_empty_write:
            with open(folder / filename, 'w+') as r:
                r.write(if_empty_write)
            return if_empty_write
        return contents

    @pytest.mark.parametrize("location", [
          {'skip': True},
          {'start': {'line': 0}},
          {'start': {'line': 1, 'column': 1}, 'end': {'line': 1, 'column': 2}}])
    def test_get_location(self, location):
        assert node.get_line_coverage(location, None, None) == (None, None, None)

    @pytest.mark.parametrize("i", [1, 2, 3])
    def test_report(self, i):
        def fixes(path):
            if path == 'ignore':
                return None
            return path

        nodejson = loads(self.readfile('node/node%s.json' % i))
        nodejson.update(base_report)

        report = node.from_json(nodejson, fixes, {}, 0, {'enable_partials': True})
        totals_dict, report_dict = report.to_database()
        report_dict = loads(report_dict)
        archive = report.to_archive()
        expected_result = loads(self.readfile('node/node%s-result.json' % i))
        # print(dumps({'totals': totals_dict, 'report': report_dict , 'archive': archive.split("<<<<< end_of_chunk >>>>>")}))
        assert expected_result['report'] == report_dict
        assert expected_result['totals'] == totals_dict
        assert expected_result['archive'] == archive.split("<<<<< end_of_chunk >>>>>")

    @pytest.mark.parametrize("name", ['inline', 'ifbinary', 'ifbinarymb'])
    def test_singles(self, name):
        record = self.readjson('node/%s.json' % name)
        report = node.from_json(record['report'], str, {}, 0, {'enable_partials': True})
        for filename, lines in record['result'].items():
            for ln, result in lines.items():
                assert loads(dumps(report[filename][int(ln)])) == result
