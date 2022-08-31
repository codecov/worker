import logging
import typing
from enum import Enum, auto

log = logging.getLogger(__name__)


class AntecessorFindingResult(Enum):
    line = auto()
    function = auto()
    file = auto()


class SingleFileSnapshotAnalyzer(object):
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
