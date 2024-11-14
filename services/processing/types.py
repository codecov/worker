from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from shared.reports.editable import EditableReport
from shared.upload.constants import UploadErrorCode


class UploadArguments(TypedDict, total=False):
    upload_id: int

    # TODO(swatinem): migrate this over to `upload_id`
    upload_pk: int

    flags: list[str]
    url: str

    name: NotRequired[str]
    reportid: NotRequired[str]
    build: NotRequired[str]
    build_url: NotRequired[str]
    job: NotRequired[str]
    service: NotRequired[str]

    # TODO(swatinem): remove these fields completely being passed from API:
    # `redis_key` being removed in https://github.com/codecov/codecov-api/pull/960
    redis_key: NotRequired[str]
    token: NotRequired[str]


class ProcessingErrorDict(TypedDict):
    code: UploadErrorCode
    params: dict[str, Any]


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
