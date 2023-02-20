import json
import pytest

from services.report.languages.pycoverage import PyCoverageProcessor
from services.report.report_processor import ReportBuilder
from tests.base import BaseTestCase

SAMPLE = {
    "meta": {
        "version": "6.4.1",
        "timestamp": "2022-06-27T01:44:41.238230",
        "branch_coverage": False,
        "show_contexts": True,
    },
    "files": {
        "another.py": {
            "executed_lines": [1, 2, 3, 4],
            "summary": {
                "covered_lines": 4,
                "num_statements": 4,
                "percent_covered": 100.0,
                "percent_covered_display": "100",
                "missing_lines": 0,
                "excluded_lines": 0,
            },
            "missing_lines": [],
            "excluded_lines": [],
            "contexts": {
                "1": [""],
                "2": [
                    "test_another.py::test_fib_simple_case|run",
                    "test_another.py::test_fib_bigger_cases|run",
                ],
                "3": [
                    "test_another.py::test_fib_simple_case|run",
                    "test_another.py::test_fib_bigger_cases|run",
                ],
                "4": ["test_another.py::test_fib_bigger_cases|run"],
            },
        },
        "source.py": {
            "executed_lines": [1, 3, 4, 5, 9],
            "summary": {
                "covered_lines": 5,
                "num_statements": 7,
                "percent_covered": 71.42857142857143,
                "percent_covered_display": "71",
                "missing_lines": 2,
                "excluded_lines": 0,
            },
            "missing_lines": [6, 10],
            "excluded_lines": [],
            "contexts": {
                "1": [""],
                "3": [""],
                "9": [""],
                "4": ["test_source.py::test_some_code|run"],
                "5": ["test_source.py::test_some_code|run"],
            },
        },
        "test_another.py": {
            "executed_lines": [1, 3, 4, 5, 7, 8],
            "summary": {
                "covered_lines": 6,
                "num_statements": 6,
                "percent_covered": 100.0,
                "percent_covered_display": "100",
                "missing_lines": 0,
                "excluded_lines": 0,
            },
            "missing_lines": [],
            "excluded_lines": [],
            "contexts": {
                "1": [""],
                "3": [""],
                "7": [""],
                "4": ["test_another.py::test_fib_simple_case|run"],
                "5": ["test_another.py::test_fib_simple_case|run"],
                "8": ["test_another.py::test_fib_bigger_cases|run"],
            },
        },
        "test_source.py": {
            "executed_lines": [1, 4, 5],
            "summary": {
                "covered_lines": 3,
                "num_statements": 3,
                "percent_covered": 100.0,
                "percent_covered_display": "100",
                "missing_lines": 0,
                "excluded_lines": 0,
            },
            "missing_lines": [],
            "excluded_lines": [],
            "contexts": {
                "1": [""],
                "4": [""],
                "5": ["test_source.py::test_some_code|run"],
            },
        },
    },
    "totals": {
        "covered_lines": 18,
        "num_statements": 20,
        "percent_covered": 90.0,
        "percent_covered_display": "90",
        "missing_lines": 2,
        "excluded_lines": 0,
    },
}


class TestPyCoverageProcessor(BaseTestCase):
    @pytest.mark.parametrize(
        "user_input, expected_result",
        [
            (
                "services/comparison/tests/unit/test_changes.py::test_get_segment_offsets[segments9-result9]",
                "services/comparison/tests/unit/test_changes.py::test_get_segment_offsets",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc[a\\\\",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc[./a\\\\b-result1]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc[./a\\n./b-result2]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc[path/target/delombok/a\\n./b-result3]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc[comma,txt\\nb-result4]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc",
            ),
            (
                'services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc[a\\n"\\\\360\\\\237\\\\215\\\\255.txt"\\nb-result5]',
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_clean_toc",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path[boring.txt-boring.txt]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path[back\\\\\\\\slash.txt-back\\\\slash.txt]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path[\\\\360\\\\237\\\\215\\\\255.txt-\\U0001f36d.txt]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path",
            ),
            (
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path[users/crovercraft/bootstrap/Icon\\\\r-users/crovercraft/bootstrap/Icon]",
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path",
            ),
            (
                'services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path[test/fixture/vcr_cassettes/clickhouse/get_breakdown_values_escaped_\\\\".json-test/fixture/vcr_cassettes/clickhouse/get_breakdown_values_escaped_".json]',
                "services/path_fixer/tests/unit/test_fixpaths.py::TestFixpaths::test_unquote_git_path",
            ),
        ],
    )
    def test_convert_testname_to_label(self, user_input, expected_result):
        processor = PyCoverageProcessor()
        assert processor._convert_testname_to_label(user_input) == expected_result

    def test_matches_content_pycoverage(self):
        p = PyCoverageProcessor()
        assert p.matches_content(SAMPLE, "", "coverage.json")
        assert not p.matches_content({"meta": True}, "", "coverage.json")
        assert not p.matches_content({"meta": {}}, "", "coverage.json")

    def test_process_pycoverage(self):
        content = SAMPLE
        p = PyCoverageProcessor()
        report_builder = ReportBuilder(
            current_yaml={"beta_groups": ["labels"]},
            sessionid=0,
            ignored_lines={},
            path_fixer=str,
        )
        report = p.process("name", content, report_builder)
        processed_report = self.convert_report_to_better_readable(report)
        assert processed_report["archive"]["source.py"][0] == (
            1,
            1,
            None,
            [[0, 1, None, None, None]],
            None,
            None,
            [(0, 1, None, ["Th2dMtk4M_codecov"])],
        )
        assert processed_report == {
            "archive": {
                "another.py": [
                    (
                        1,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        2,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [
                            (0, 1, None, ["test_another.py::test_fib_simple_case"]),
                            (0, 1, None, ["test_another.py::test_fib_bigger_cases"]),
                        ],
                    ),
                    (
                        3,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [
                            (0, 1, None, ["test_another.py::test_fib_simple_case"]),
                            (0, 1, None, ["test_another.py::test_fib_bigger_cases"]),
                        ],
                    ),
                    (
                        4,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["test_another.py::test_fib_bigger_cases"])],
                    ),
                ],
                "source.py": [
                    (
                        1,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        3,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        4,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["test_source.py::test_some_code"])],
                    ),
                    (
                        5,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["test_source.py::test_some_code"])],
                    ),
                    (
                        6,
                        0,
                        None,
                        [[0, 0, None, None, None]],
                        None,
                        None,
                        [(0, 0, None, [])],
                    ),
                    (
                        9,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        10,
                        0,
                        None,
                        [[0, 0, None, None, None]],
                        None,
                        None,
                        [(0, 0, None, [])],
                    ),
                ],
                "test_another.py": [
                    (
                        1,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        3,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        4,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["test_another.py::test_fib_simple_case"])],
                    ),
                    (
                        5,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["test_another.py::test_fib_simple_case"])],
                    ),
                    (
                        7,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        8,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["test_another.py::test_fib_bigger_cases"])],
                    ),
                ],
                "test_source.py": [
                    (
                        1,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        4,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["Th2dMtk4M_codecov"])],
                    ),
                    (
                        5,
                        1,
                        None,
                        [[0, 1, None, None, None]],
                        None,
                        None,
                        [(0, 1, None, ["test_source.py::test_some_code"])],
                    ),
                ],
            },
            "report": {
                "files": {
                    "another.py": [
                        0,
                        [0, 4, 4, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        [[0, 4, 4, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "source.py": [
                        1,
                        [0, 7, 5, 2, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0],
                        [[0, 7, 5, 2, 0, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "test_another.py": [
                        2,
                        [0, 6, 6, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        [[0, 6, 6, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                    "test_source.py": [
                        3,
                        [0, 3, 3, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        [[0, 3, 3, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                        None,
                    ],
                },
                "sessions": {},
            },
            "totals": {
                "f": 4,
                "n": 20,
                "h": 18,
                "m": 2,
                "p": 0,
                "c": "90.00000",
                "b": 0,
                "d": 0,
                "M": 0,
                "s": 0,
                "C": 0,
                "N": 0,
                "diff": None,
            },
        }
