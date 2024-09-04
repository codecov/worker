from services.report.languages import rlang
from services.report.report_builder import ReportBuilder
from test_utils.base import BaseTestCase

json = {
    "uploader": "R",
    "files": [
        {"name": "source/cov.r", "coverage": [None, 1, 0]},
        {"name": "source/app.r", "coverage": [None, 1]},
    ],
}


class TestRlang(BaseTestCase):
    def test_report(self):
        def fixes(path):
            assert path in ("source/cov.r", "source/app.r")
            return path

        report_builder = ReportBuilder(
            current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=fixes
        )
        report = rlang.from_json(json, report_builder.create_report_builder_session(""))

        processed_report = self.convert_report_to_better_readable(report)
        expected_result_archive = {
            "source/app.r": [(1, 1, None, [[0, 1, None, None, None]], None, None)],
            "source/cov.r": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 0, None, [[0, 0, None, None, None]], None, None),
            ],
        }

        assert expected_result_archive == processed_report["archive"]
