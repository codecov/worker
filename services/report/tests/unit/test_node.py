from ddt import data, ddt
from json import loads, dumps

from tests.base import TestCase
from app.tasks.reports.languages import node


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


@ddt
class Test(TestCase):
    @data({'skip': True},
          {'start': {'line': 0}},
          {'start': {'line': 1, 'column': 1}, 'end': {'line': 1, 'column': 2}})
    def test_get_location(self, location):
        assert node.get_line_coverage(location, None, None) == (None, None, None)

    @data(1, 2, 3)
    def test_report(self, i):
        def fixes(path):
            if path == 'ignore':
                return None
            return path

        nodejson = loads(self.readfile('tests/unittests/tasks/reports/node/node%s.json' % i))
        nodejson.update(base_report)

        report = node.from_json(nodejson, fixes, {}, 0, {'enable_partials': True})
        report = self.v3_to_v2(report)

        self.validate.report(report)

        # with open('/Users/peak/Documents/codecov/codecov.io/tests/unittests/tasks/reports/node/node%s-result.json' % i, 'w+') as w:
        #     w.write(dumps(report, indent=2, sort_keys=True))

        assert report == loads(self.readfile('tests/unittests/tasks/reports/node/node%s-result.json' % i))

    @data('inline', 'ifbinary', 'ifbinarymb')
    def test_singles(self, name):
        record = self.readjson('tests/unittests/tasks/reports/node/%s.json' % name)
        report = node.from_json(record['report'], str, {}, 0, {'enable_partials': True})
        for filename, lines in record['result'].iteritems():
            for ln, result in lines.iteritems():
                assert loads(dumps(report[filename][int(ln)])) == result
