from ddt import data, ddt
from tests.base import TestCase
from app.tasks.reports.languages import dlst


RAW = '''       |empty
      1|coverage
0000000|missed
this is not line....
source file.d is 77% covered'''

result = {
    "files": {
        "src/file.d": {
            "l": {
                "2": {"c": 1, "s": [[0, 1, None, None, None]]},
                "3": {"c": 0, "s": [[0, 0, None, None, None]]}
            }
        }
    }
}


@ddt
class Test(TestCase):
    @data('src/file.lst', 'bad/path.lst', '')
    def test_report(self, filename):
        def fixer(path):
            if path in ('file.d', 'src/file.d'):
                return 'src/file.d'

        report = dlst.from_string(filename, RAW, fixer, {}, 0)
        report = self.v3_to_v2(report)
        self.validate.report(report)
        assert result == report

    def test_none(self):
        report = dlst.from_string(None, '   1|test\nignore is 100% covered', lambda a: False, {}, 0)
        assert None is report
