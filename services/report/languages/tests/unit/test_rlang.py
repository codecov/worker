from services.report.languages import rlang
from test_utils.base import BaseTestCase

from . import create_report_builder_session

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

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        rlang.from_json(json, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"] == {
            "source/app.r": [(1, 1, None, [[0, 1, None, None, None]], None, None)],
            "source/cov.r": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 0, None, [[0, 0, None, None, None]], None, None),
            ],
        }
