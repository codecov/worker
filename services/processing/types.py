from dataclasses import dataclass
from typing import NotRequired, TypedDict

from shared.reports.editable import EditableReport

from services.report import ProcessingErrorDict


class UploadArguments(TypedDict):
    upload_id: int

    # TODO(swatinem): migrate this over to `upload_id`
    upload_pk: int


class ProcessingResult(TypedDict):
    upload_id: int
    arguments: UploadArguments
    successful: bool
    error: NotRequired[ProcessingErrorDict]


@dataclass
class IntermediateReport:
    upload_id: int
    """
    The `Upload` id for which this report was loaded.
    """

    report: EditableReport
    """
    The loaded Report.
    """


@dataclass
class MergeResult:
    session_mapping: dict[int, int]
    """
    This is a mapping from the input `upload_id` to the output `session_id`
    as it exists in the merged "master Report".
    """

    deleted_sessions: set[int]
    """
    The Set of carryforwarded `session_id`s that have been removed from the "master Report".
    """
