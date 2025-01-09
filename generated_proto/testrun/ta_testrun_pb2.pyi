from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class TestRun(_message.Message):
    __slots__ = (
        "timestamp",
        "name",
        "classname",
        "testsuite",
        "computed_name",
        "outcome",
        "failure_message",
        "duration_seconds",
        "repoid",
        "commit_sha",
        "branch_name",
        "flags",
        "filename",
        "framework",
    )
    class Outcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        PASSED: _ClassVar[TestRun.Outcome]
        FAILED: _ClassVar[TestRun.Outcome]
        SKIPPED: _ClassVar[TestRun.Outcome]

    PASSED: TestRun.Outcome
    FAILED: TestRun.Outcome
    SKIPPED: TestRun.Outcome
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    CLASSNAME_FIELD_NUMBER: _ClassVar[int]
    TESTSUITE_FIELD_NUMBER: _ClassVar[int]
    COMPUTED_NAME_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    FAILURE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DURATION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    REPOID_FIELD_NUMBER: _ClassVar[int]
    COMMIT_SHA_FIELD_NUMBER: _ClassVar[int]
    BRANCH_NAME_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    FRAMEWORK_FIELD_NUMBER: _ClassVar[int]
    timestamp: int
    name: str
    classname: str
    testsuite: str
    computed_name: str
    outcome: TestRun.Outcome
    failure_message: str
    duration_seconds: float
    repoid: int
    commit_sha: str
    branch_name: str
    flags: _containers.RepeatedScalarFieldContainer[str]
    filename: str
    framework: str
    def __init__(
        self,
        timestamp: _Optional[int] = ...,
        name: _Optional[str] = ...,
        classname: _Optional[str] = ...,
        testsuite: _Optional[str] = ...,
        computed_name: _Optional[str] = ...,
        outcome: _Optional[_Union[TestRun.Outcome, str]] = ...,
        failure_message: _Optional[str] = ...,
        duration_seconds: _Optional[float] = ...,
        repoid: _Optional[int] = ...,
        commit_sha: _Optional[str] = ...,
        branch_name: _Optional[str] = ...,
        flags: _Optional[_Iterable[str]] = ...,
        filename: _Optional[str] = ...,
        framework: _Optional[str] = ...,
    ) -> None: ...
