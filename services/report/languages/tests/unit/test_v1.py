from json import loads

import pytest

from helpers.exceptions import CorruptRawReportError
from services.report.languages import v1
from tests.base import BaseTestCase

txt = """
{
    "coverage": {
        "source": [null, 1],
        "file": {"1": 1, "2": "1", "3": true, "4": "1/2"},
        "empty": {}
    },
    "messages": {
        "source": {
            "1": "Message"
        }
    }
}

"""

invalid_report = """{
    "coverage": {
        "/home/repo/app/scable/channel.rb": {
            "lines": [
                "1",
                "1",
                "None",
                "None"
            ]
        },
        "/home/repo/app/scable/connection.rb": {},
        "/home/repo/app/controllers/api/base_controller.rb": {},
        "/home/path/to/base_controller.rb": {},
        "/home/path/to/defaults.rb": {},
        "/home/path/to/users_controller.rb": {},
        "/home/path/to/validators/invoice_date.rb": {},
        "/home/path/to/validators/max_length.rb": {},
        "/home/repo/app/lib/parser/json_api.rb": {},
        "/home/repo/lib/exceptions.rb": {
            "lines": [
                "1",
                "1",
                "1",
                "None",
                "1",
                "1",
                "1",
                "1",
                "1",
                "1"
            ]
        }
    },
    "timestamp": 1588372645
}
"""


class TestVOne(BaseTestCase):
    def test_report(self):
        def fixes(path):
            assert path in ("source", "file", "empty")
            return path

        report = v1.from_json(loads(txt), fixes, {}, 0, {})
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
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
        assert v1.from_json({"coverage": "<string>"}, str, {}, 0, {}) is None

    def test_report_that_looks_valid_but_isnt(self):
        with pytest.raises(CorruptRawReportError) as ex:
            v1.from_json(loads(invalid_report), lambda x: x, {}, 0, {})
        assert ex.value.expected_format == "v1"
        assert (
            ex.value.corruption_error
            == "file dictionaries expected to have integers, not strings"
        )
