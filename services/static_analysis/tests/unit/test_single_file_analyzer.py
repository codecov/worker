from services.static_analysis.single_file_analyzer import (
    AntecessorFindingResult,
    SingleFileSnapshotAnalyzer,
)

# While the structure of this is correct, the data itself was manually edited
# to make interesting test cases
sample_input_data = {
    "empty_lines": [4, 8, 11],
    "warnings": [],
    "filename": "source.py",
    "functions": [
        {
            "identifier": "some_function",
            "start_line": 5,
            "end_line": 10,
            "code_hash": "e4b52b6da12184142fcd7ff2c8412662",
            "complexity_metrics": {
                "conditions": 1,
                "mccabe_cyclomatic_complexity": 2,
                "returns": 1,
                "max_nested_conditional": 1,
            },
        }
    ],
    "hash": "811d0016249a5b1400a685164e5295de",
    "language": "python",
    "number_lines": 11,
    "statements": [
        (
            1,
            {
                "line_surety_ancestorship": None,
                "start_column": 0,
                "line_hash": "55c30cf01e202728b6952e9cba304798",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            2,
            {
                "line_surety_ancestorship": 1,
                "start_column": 4,
                "line_hash": "1d7be9f2145760a59513a4049fcd0d1c",
                "len": 1,
                "extra_connected_lines": (),
            },
        ),
        (
            5,
            {
                "line_surety_ancestorship": None,
                "start_column": 4,
                "line_hash": "1d7be9f2145760a59513a4049fcd0d1c",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
        (
            6,
            {
                "line_surety_ancestorship": 5,
                "start_column": 4,
                "line_hash": "52f98812dca4687f18373b87433df695",
                "len": 0,
                "extra_connected_lines": (14,),
            },
        ),
        (
            7,
            {
                "line_surety_ancestorship": 6,
                "start_column": 4,
                "line_hash": "52f98812dca4687f18373b87433df695",
                "len": 0,
                "extra_connected_lines": (),
            },
        ),
    ],
    "definition_lines": [(4, 6)],
    "import_lines": [],
}


def test_simple_single_file_snapshot_analyzer_get_corresponding_executable_line():
    sfsa = SingleFileSnapshotAnalyzer("filepath", sample_input_data)
    assert sfsa.get_corresponding_executable_line(3) == 2
    assert sfsa.get_corresponding_executable_line(2) == 2
    assert sfsa.get_corresponding_executable_line(4) is None
    assert sfsa.get_corresponding_executable_line(14) == 6


def test_get_antecessor_executable_line():
    sfsa = SingleFileSnapshotAnalyzer("filepath", sample_input_data)
    assert sfsa.get_antecessor_executable_line(7, lines_to_not_consider=[6, 7]) == (
        AntecessorFindingResult.line,
        5,
    )
    assert sfsa.get_antecessor_executable_line(2, lines_to_not_consider=[1, 2]) == (
        AntecessorFindingResult.file,
        "filepath",
    )
    assert sfsa.get_antecessor_executable_line(5, lines_to_not_consider=[5]) == (
        AntecessorFindingResult.function,
        "some_function",
    )
