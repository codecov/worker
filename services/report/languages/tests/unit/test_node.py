from json import loads, dumps, JSONEncoder
from fractions import Fraction
import dataclasses

import pytest
from pathlib import Path
from tests.base import BaseTestCase
from services.report.languages import node


here = Path(__file__)
folder = here.parent

base_report = {
    "ignore": {},
    "empty": {
        "statementMap": {"1": {"skip": True}},
        "branchMap": {"1": {"skip": True}},
        "fnMap": {"1": {"skip": True}},
    },
}


class OwnEncoder(JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.astuple(o)
        if isinstance(o, Fraction):
            return str(o)
        return super().default(o)


class TestNodeProcessor(BaseTestCase):
    def readjson(self, filename):
        with open(folder / filename, "r") as d:
            contents = loads(d.read())
            return contents

    def readfile(self, filename, if_empty_write=None):
        with open(folder / filename, "r") as r:
            contents = r.read()

        # codecov: assert not covered start [FUTURE new concept]
        if contents.strip() == "" and if_empty_write:
            with open(folder / filename, "w+") as r:
                r.write(if_empty_write)
            return if_empty_write
        return contents

    @pytest.mark.parametrize(
        "location",
        [
            {"skip": True},
            {"start": {"line": 0}},
            {"start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 2}},
        ],
    )
    def test_get_location(self, location):
        assert node.get_line_coverage(location, None, None) == (None, None, None)

    @pytest.mark.parametrize("i", [1, 2, 3])
    def test_report(self, i):
        def fixes(path):
            if path == "ignore":
                return None
            return path

        nodejson = loads(self.readfile("node/node%s.json" % i))
        nodejson.update(base_report)

        report = node.from_json(nodejson, fixes, {}, 0, {"enable_partials": True})
        totals_dict, report_dict = report.to_database()
        report_dict = loads(report_dict)
        archive = report.to_archive()
        expected_result = loads(self.readfile("node/node%s-result.json" % i))
        assert expected_result["report"] == report_dict
        assert expected_result["totals"] == totals_dict
        assert expected_result["archive"] == archive.split("<<<<< end_of_chunk >>>>>")

    @pytest.mark.parametrize("name", ["inline", "ifbinary", "ifbinarymb"])
    def test_singles(self, name):
        record = self.readjson("node/%s.json" % name)
        report = node.from_json(record["report"], str, {}, 0, {"enable_partials": True})
        for filename, lines in record["result"].items():
            for ln, result in lines.items():
                assert loads(dumps(report[filename][int(ln)], cls=OwnEncoder)) == result

    def test_matches_content_bad_user_input(self):
        processor = node.NodeProcessor()
        user_input_1 = {"filename_1": {}, "filename_2": 1}
        assert not processor.matches_content(
            user_input_1, "first_line", "coverage.json"
        )
        user_input_2 = {"filename_1": "adsadasddsa", "filename_2": {}}
        assert not processor.matches_content(
            user_input_2, "first_line", "coverage.json"
        )
        user_input_3 = "filename: 1"
        assert not processor.matches_content(
            user_input_3, "first_line", "coverage.json"
        )

    def test_matches_content_good_user_input(self):
        processor = node.NodeProcessor()
        user_input_1 = {"filename_1": {}, "filename_2": {"statementMap": {}}}
        assert processor.matches_content(user_input_1, "first_line", "coverage.json")
        user_input_2 = {"filename_1": {"statementMap": 1}, "filename_2": {}}
        assert processor.matches_content(user_input_2, "first_line", "coverage.json")

    def test_no_statement_map(self):
        user_input = {
            "filename.py": {
                "branches": {"covered": 0, "pct": 100, "skipped": 0, "total": 0},
                "functions": {"covered": 0, "pct": 0, "skipped": 0, "total": 1},
                "lines": {"covered": 2, "pct": 66.67, "skipped": 0, "total": 3},
                "statements": {"covered": 2, "pct": 66.67, "skipped": 0, "total": 3},
            }
        }
        res = node.from_json(user_input, lambda x: x, {}, 0, {"enable_partials": False})
        assert res.is_empty()
