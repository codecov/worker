import dataclasses
from fractions import Fraction
from json import JSONEncoder, dumps, loads
from pathlib import Path

import pytest

from services.report.languages import node
from test_utils.base import BaseTestCase

from . import create_report_builder_session

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
        "location, expected_result",
        [
            ({"skip": True}, (None, None, None)),
            ({"start": {"line": 0}}, (None, None, None)),
            (
                {"start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 2}},
                (None, None, None),
            ),
            (
                {"start": {"line": 1, "column": 1}, "end": {"line": 10, "column": 2}},
                (1, None, None),
            ),
        ],
    )
    def test_get_location(self, location, expected_result):
        assert node.get_line_coverage(location, None, None) == expected_result

    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"skip": True}, None),
            ({"start": {"line": 0}}, None),
            ({"start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 2}}, 1),
        ],
    )
    def test_location_to_int(self, location, expected):
        assert node._location_to_int(location) == expected

    @pytest.mark.parametrize("i", [1, 2, 3])
    def test_report(self, i):
        def fixes(path):
            if path == "ignore":
                return None
            return path

        nodejson = loads(self.readfile("node/node%s.json" % i))
        nodejson.update(base_report)

        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"javascript": {"enable_partials": True}}},
            path_fixer=fixes,
        )
        node.from_json(nodejson, report_builder_session)
        report = report_builder_session.output_report()

        totals_dict, report_dict = report.to_database()
        report_dict = loads(report_dict)
        archive = report.to_archive()

        expected_result = loads(self.readfile("node/node%s-result.json" % i))

        assert report_dict == expected_result["report"]
        assert totals_dict == expected_result["totals"]

        assert archive.split("<<<<< end_of_chunk >>>>>") == expected_result["archive"]

    @pytest.mark.parametrize("name", ["inline", "ifbinary", "ifbinarymb"])
    def test_singles(self, name):
        record = self.readjson("node/%s.json" % name)
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"javascript": {"enable_partials": True}}},
        )
        node.from_json(record["report"], report_builder_session)
        report = report_builder_session.output_report()

        for filename, lines in record["result"].items():
            for ln, result in lines.items():
                assert loads(dumps(report[filename][int(ln)], cls=OwnEncoder)) == result

    @pytest.mark.parametrize(
        "name,result",
        [
            (
                "inline",
                {
                    "file.js": {
                        "728": [
                            8,
                            None,
                            [[0, 8, None, None, None]],
                            None,
                            None,
                            None,
                        ]
                    }
                },
            ),
            (
                "ifbinary",
                {
                    "file.js": {
                        "731": [
                            8,
                            None,
                            [
                                [
                                    0,
                                    8,
                                    None,
                                    None,
                                    None,
                                ]
                            ],
                            None,
                            None,
                            None,
                        ]
                    }
                },
            ),
        ],
    )
    def test_singles_no_partials_statement_map(self, name, result):
        record = self.readjson("node/%s.json" % name)
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"javascript": {"enable_partials": False}}},
        )
        # In this test in particular we're trying to test the statementMap coverage in `from_json`
        # Because the branchMap is analysed afterwards it overwrites the line coverage there.
        # So forcing the statementMap only
        record["report"]["file.js"].pop("branchMap")
        node.from_json(record["report"], report_builder_session)
        report = report_builder_session.output_report()
        for filename, lines in result.items():
            for ln, result in lines.items():
                assert loads(dumps(report[filename][int(ln)], cls=OwnEncoder)) == result

    @pytest.mark.parametrize(
        "name,result",
        [
            (
                "inline",
                {
                    "file.js": {
                        "728": [
                            8,
                            "b",
                            [[0, 8, None, None, None]],
                            None,
                            None,
                            None,
                        ]
                    }
                },
            ),
            (
                "ifbinary",
                {
                    "file.js": {
                        "731": [
                            8,
                            "b",
                            [
                                [
                                    0,
                                    8,
                                    None,
                                    None,
                                    None,
                                ]
                            ],
                            None,
                            None,
                            None,
                        ]
                    }
                },
            ),
        ],
    )
    def test_singles_no_partials_branch_map(self, name, result):
        record = self.readjson("node/%s.json" % name)
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"javascript": {"enable_partials": False}}},
        )
        node.from_json(record["report"], report_builder_session)
        report = report_builder_session.output_report()
        for filename, lines in result.items():
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
        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"javascript": {"enable_partials": True}}},
        )

        node.from_json(user_input, report_builder_session)
        report = report_builder_session.output_report()

        assert report.is_empty()
