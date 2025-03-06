import logging
import typing
from enum import Enum, auto

log = logging.getLogger(__name__)


class AntecessorFindingResult(Enum):
    line = auto()
    function = auto()
    file = auto()


class SingleFileSnapshotAnalyzer(object):
    """
    This is an analyzer for a single snapshot of a file (meaning a version of a file in
        a particular moment of time)

    For now, the expected structure of the file snapshot is
        (there can be more fields, but those are the ones being used in this context):

    empty_lines:
        a list of lines that we know are empty
    functions:
        a list of functions/methods in this file, and its details.
        The structure of a function is (some fields declared here might not be used):
            declaration_line: The line where the function is declared
            identifier: A unique identifier (in the global context) for the function
                Something that can later help us tell that a moved function is
                still the same function
            start_line: The line where the function code starts
            end_line: The line where the function code ends
            code_hash: A hash of the function body that helps us tell when it changed
            complexity_metrics: Some complexity metrics not used here
    hash: The hash code of the file so its easy to tell when it has changed
    language: The programming language of the file (not used here)
    number_lines: The number of lines this file has
    statements: A list of statements in this file. A statement structure is a tuple of two
        elements:
        - The first element is the line number where that statement is
        - The second element is a dict with more information about that line:
            -   line_surety_ancestorship: It's the number of the line that we know
                    will be executed before this statement happens. Like
                    "We are sure this line will be an ancestor to this statement"
                    This is a way to construct a light version of the flowchart graph
                    of the file
                start_column: The column where this code starts
                line_hash: The hash of this line (to later tell line changes vs code change)
                len: The number of lines (in addition to this one that this code entails)
                extra_connected_lines: Which lines are not contiguous to this, but should
                    be considered to affect this line. One example is the "else" that indirectly
                    affects the "if", because it's like part of the if "jumping logic"
    definition_lines: The lines where things (like classes, functions, enums) are defined
        - Those don't have much use for now
    import_lines: The lines where imports are. It's useful for other analysis.
        But not this one

    We will eventually having a schema to validate data against this so we can ensure data
        is valid when we use it. The schema will be better documentation of the format than this
    """

    def __init__(self, filepath, analysis_file_data):
        self._filepath = filepath
        self._analysis_file_data = analysis_file_data
        self._statement_mapping = dict(analysis_file_data["statements"])

    def get_corresponding_executable_line(self, line_number: int) -> int:
        for that_line, statement_data in self._analysis_file_data["statements"]:
            if (
                that_line <= line_number
                and that_line + statement_data["len"] >= line_number
            ):
                return that_line
            if line_number in statement_data["extra_connected_lines"]:
                return that_line
        # This is a logging.warning for now while we implement things
        # But there will be a really reasonable case where customers
        # change no code. So it won't have a corresponding executable line
        log.warning(
            "Not able to find corresponding executable line",
            extra=dict(
                filepath_=self._filepath,
                line_number=line_number,
                allstuff=self._analysis_file_data["statements"],
            ),
        )
        return None

    def get_antecessor_executable_line(
        self, line_number: int, lines_to_not_consider: typing.List[int]
    ) -> int:
        current_line = line_number
        while (
            current_line in lines_to_not_consider
            and self._statement_mapping.get(current_line, {}).get(
                "line_surety_ancestorship"
            )
            and current_line
            != self._statement_mapping.get(current_line, {}).get(
                "line_surety_ancestorship"
            )
        ):
            current_line = self._statement_mapping.get(current_line, {}).get(
                "line_surety_ancestorship"
            )
        if current_line not in lines_to_not_consider:
            return (AntecessorFindingResult.line, current_line)
        for f in self._analysis_file_data["functions"]:
            if (
                f.get("start_line") <= current_line
                and f.get("end_line") >= current_line
            ):
                return (AntecessorFindingResult.function, f["identifier"])
        log.warning(
            "Somehow not able to find antecessor line",
            extra=dict(
                filepath_=self._filepath,
                line_number=line_number,
                lines_to_not_consider=lines_to_not_consider,
                allstuff=self._analysis_file_data["statements"],
            ),
        )
        return (AntecessorFindingResult.file, self._filepath)

    def find_function_by_identifier(self, function_identifier):
        for func in self._analysis_file_data["functions"]:
            if func["identifier"] == function_identifier:
                return func
        return None
