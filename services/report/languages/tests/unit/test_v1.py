import pytest

from helpers.exceptions import CorruptRawReportError
from services.report.languages import v1
from test_utils.base import BaseTestCase

from . import create_report_builder_session

json = {
    "coverage": {
        "source": [None, 1],
        "file": {"1": 1, "2": "1", "3": True, "4": "1/2"},
        "empty": {},
    },
    "messages": {"source": {"1": "Message"}},
}

alternative_report_format = {
    "coverage": {
        "/home/repo/app/scable/channel.rb": {"lines": [1, 1, None, None]},
        "/home/repo/app/scable/something.rb": {},
        "/home/repo/app/scable/something_else.rb": {"lines": []},
        "/home/repo/lib/exceptions.rb": {"lines": [1, 0, 10, None]},
    },
    "timestamp": 1588372645,
}


class TestVOne(BaseTestCase):
    def test_report(self):
        def fixes(path):
            assert path in ("source", "file", "empty")
            return path

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        v1.from_json(json, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "file": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 1, None, [[0, 1, None, None, None]], None, None),
                (3, True, "b", [[0, True, None, None, None]], None, None),
                (4, "1/2", "b", [[0, "1/2", None, None, None]], None, None),
            ],
            "source": [(1, 1, None, [[0, 1, None, None, None]], None, None)],
        }

        assert expected_result_archive == processed_report["archive"]

    def test_not_list(self):
        report_builder_session = create_report_builder_session()
        v1.from_json({"coverage": "<string>"}, report_builder_session)
        report = report_builder_session.output_report()

        assert not report

    def test_report_with_alternative_format(self):
        report_builder_session = create_report_builder_session()
        v1.from_json(alternative_report_format, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "/home/repo/app/scable/channel.rb": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 1, None, [[0, 1, None, None, None]], None, None),
            ],
            "/home/repo/lib/exceptions.rb": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 0, None, [[0, 0, None, None, None]], None, None),
                (3, 10, None, [[0, 10, None, None, None]], None, None),
            ],
        }
        assert expected_result_archive == processed_report["archive"]

    def test_corrupted_report(self):
        corrupted_report = {
            "coverage": {
                "source": [None, 1],
                "file": {"file1": 1, "file2": 2},
            }
        }
        report_builder_session = create_report_builder_session()

        with pytest.raises(CorruptRawReportError) as e:
            v1.from_json(corrupted_report, report_builder_session)

        exp = e.value
        assert (
            exp.corruption_error
            == "file dictionaries expected to have integers, not strings"
        )
        assert exp.expected_format == "v1"
