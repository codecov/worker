import typing
from dataclasses import dataclass
from enum import Enum

import sentry_sdk

from services.comparison.changes import get_segment_offsets


class DiffChangeType(Enum):
    new = "new"
    deleted = "deleted"
    modified = "modified"
    binary = "binary"

    @classmethod
    def get_from_string(cls, string_value):
        for i in cls:
            if i.value == string_value:
                return i


@dataclass
class DiffChange(object):
    __slots__ = (
        "before_filepath",
        "after_filepath",
        "change_type",
        "lines_only_on_base",
        "lines_only_on_head",
    )
    before_filepath: typing.Optional[str]
    after_filepath: typing.Optional[str]
    change_type: DiffChangeType
    lines_only_on_base: typing.Optional[typing.List[int]]
    lines_only_on_head: typing.Optional[typing.List[int]]

    def map_base_line_to_head_line(self, base_line: int):
        return self._map_this_to_other(
            base_line, self.lines_only_on_base, self.lines_only_on_head
        )

    def map_head_line_to_base_line(self, head_line: int):
        return self._map_this_to_other(
            head_line, self.lines_only_on_head, self.lines_only_on_base
        )

    def _map_this_to_other(self, line_number, this, other):
        if self.change_type in (
            DiffChangeType.binary,
            DiffChangeType.deleted,
            DiffChangeType.new,
        ):
            return None
        if line_number in this:
            return None
        smaller_lines = sum(1 for x in this if x < line_number)
        current_point = line_number - smaller_lines
        for lh in other:
            if lh <= current_point:
                current_point += 1
        return current_point


# NOTE: Computationally intensive.
@sentry_sdk.trace
def parse_git_diff_json(diff_json, pr_files=None) -> typing.List[DiffChange]:
    for key, value in diff_json["diff"]["files"].items():
        change_type = DiffChangeType.get_from_string(value["type"])
        after = None if change_type == DiffChangeType.deleted else key

        if (
            after is None
            or (
                pr_files
                and not any(
                    pr_file["filename"] == after for pr_file in pr_files
                )
            )
        ):
            continue

        before = (
            None if change_type == DiffChangeType.new else (value.get("before") or key)
        )
        _, additions, removals = (
            get_segment_offsets(value["segments"])
            if change_type not in (DiffChangeType.binary, DiffChangeType.deleted)
            else (None, None, None)
        )
        yield DiffChange(
            before_filepath=before,
            after_filepath=after,
            change_type=DiffChangeType.get_from_string(value["type"]),
            lines_only_on_base=sorted(removals) if removals is not None else None,
            lines_only_on_head=sorted(additions) if additions is not None else None,
        )
