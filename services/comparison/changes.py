import dataclasses
import logging
from collections import defaultdict
from typing import Any, Dict, Iterator, List, Tuple, Union

import sentry_sdk
from shared.helpers.numeric import ratio
from shared.reports.resources import Report
from shared.reports.types import Change, ReportTotals
from shared.utils.merge import line_type

log = logging.getLogger(__name__)


def diff_totals(base, head, absolute=None) -> Union[bool, None, ReportTotals]:
    if head is None:
        return False  # file deleted

    elif base is None:
        return True  # new file

    elif base == head:
        return None  # same same

    head_tuple = dataclasses.astuple(head)
    base_tuple = dataclasses.astuple(base)

    diff_tuple = [
        (int(float(head_tuple[i] or 0)) - int(float(base_tuple[i] or 0)))
        for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11)
    ]
    diff = ReportTotals(*diff_tuple)
    if absolute and absolute.coverage is not None:
        # ratio(before.hits + changed.hits, before.lines, changed.lines) - coverage before
        #   = actual coveage change
        hits = absolute.hits + diff.hits
        diff.coverage = float(
            ratio(
                hits,
                (
                    hits
                    + absolute.misses
                    + diff.misses
                    + absolute.partials
                    + diff.partials
                ),
            )
        ) - float(absolute.coverage)
    else:
        diff.coverage = float(head.coverage) - float(base.coverage)
    return ReportTotals(*diff)


def get_segment_offsets(segments) -> Tuple[Dict[int, Any], List[int]]:
    offsets = defaultdict(lambda: 0)
    additions = []
    removals = []
    # loop through the segments
    for seg in segments:
        # get the starting line number
        start = int(seg["header"][2]) or 1
        offset_l = 0  # used to offset the segment line number (not real line numbers)
        offset_r = 0  # used to offset the segment line number (not real line numbers)
        base_start = (
            int(seg["header"][0] if seg["header"][0] and seg["header"][0] != " " else 1)
            or 1
        )
        starting_diff = start - base_start
        # loop through all the lines
        for ln, line in enumerate(seg["lines"], start=start):
            l0 = line[0]
            if l0 == "-":
                removals.append(ln + offset_l - starting_diff)
                offsets[ln + offset_r] += 1
                offset_r -= 1

            elif l0 == "+":
                additions.append(ln + offset_r)
                offsets[ln + offset_r] -= 1
                offset_l -= 1
    return dict([(k, v) for k, v in offsets.items() if v != 0]), additions, removals


@sentry_sdk.trace
def get_changes(
    base_report: Report, head_report: Report, diff_json: dict[str, Any] | None
) -> list[Change] | None:
    """

    Please bear with me because I didnt write the function, so what I know is from using it
        and trying to unit testing it.

    What this function does is calculate the "unexpected" changes on coverage between two reports.
        Unexpected changes are changes that do NOT arise from the diff.
        That means, for example, that:
            - If you delete the file between BASE and HEAD, it is expected that the coverage from
                that file will vanish on HEAD, so it does not show up on changes list
            - Added files are also ignored on the changes list.
            - The coverage changes that happen inside the git diff are also expected, so
                they dont show up here
            - Files that are not in the diff will show up here
            - Files that are in the diff, but had the change happen outside the diff will show up
                here
            - Renaming the file will also be properly handled here such that, if a file is renamed,
                we compare the `original_name` ReportFile in the base report and
                the `new_name` ReportFile in the head report

    For a better understanding of it, see the unit tests covering this function

    Args:
        base_report (Report): The report for the base commit
        head_report (Report): The report for the head commit
        diff_json (Mapping[str, Any]): The diff between the base and head commit as returned by torngit

    Returns:
        List[Change]: A list of unexpected changes between base_report and head_report
    """
    if base_report is None or head_report is None:
        return None

    changes = []
    base_files = set(base_report.files)
    head_files = set(head_report.files)
    diff_keys = set(diff_json["files"].keys()) if diff_json else set()

    # moved files
    moved_files = (
        set([d["before"] for k, d in diff_json["files"].items() if d.get("before")])
        if diff_json
        else set()
    )
    # deleted files
    missing_files = base_files - head_files - diff_keys - moved_files
    # added files
    new_files = head_files - base_files - diff_keys - moved_files

    # find modified !diff files
    for _file in head_report:
        filename = _file.name
        # skip [new] + [missing]
        if filename in missing_files or filename in new_files:
            continue

        diff = diff_json["files"].get(filename) if diff_json is not None else None
        base_report_file = base_report.get(
            (diff.get("before") or filename) if diff else filename
        )
        if not base_report_file:
            if diff is None:
                # Seems to only happen when there is a 'moved file' in a weird situation
                log.info(
                    "File not in the diff, not in base, but still not a 'new_file'",
                    extra=dict(
                        diff_keys=sorted(diff_keys),
                        missing_filename=filename,
                        base_is_none=base_report_file is None,
                        moved_files=sorted(moved_files),
                    ),
                )
                new_files.add(filename)
                continue
            if diff.get("type") == "new":
                # File is lacking at base, present at head
                # Diff says it's because it's new
                # This is expected
                continue
            _, additions, _ = get_segment_offsets(diff["segments"])
            additions = set(additions)
            if any(ln not in additions for ln, _ in _file.lines):
                # file has new coverage lines that are not accounted by the diff
                new_files.add(filename)
                continue

        lines = list(
            iter_changed_lines(
                base_report_file=base_report_file,
                head_report_file=_file,
                diff=diff,
                yield_line_numbers=False,
            )
        )

        if any(lines):
            # only if there are any lines that changed
            lines = zip(*lines)
            changes.append(
                Change(
                    path=filename,
                    in_diff=bool(diff),
                    old_path=diff.get("before") if diff else None,
                    totals=diff_totals(
                        get_totals_from_list(next(lines)),
                        get_totals_from_list(next(lines)),
                        base_report_file.totals,
                    ),
                )
            )
    vanished_base_files = {
        d.get("before") or k: (k, d)
        for (k, d) in diff_json["files"].items()
        if head_report.get(k) is None
        and base_report.get(d.get("before") or k) is not None
    }
    for possibly_deleted_filename, data in vanished_base_files.items():
        head_name, diff = data
        # these are files that are present on base, not present on head
        # and are possibly accounted by the diff
        # But to know that for sure we need to know that every line lost is accounted
        # by the diff
        if diff.get("type") != "deleted":
            base_report_file = base_report.get(possibly_deleted_filename)
            present_lines_on_base = set(x[0] for x in base_report_file.lines)
            _, _, line_removals = get_segment_offsets(diff["segments"])
            lines_unnaccounted_for = present_lines_on_base - set(line_removals)
            if lines_unnaccounted_for:
                changes.append(Change(path=head_name, deleted=True))

    # [deleted] [~~diff~~] == missing reports
    # left over deleted files
    # this one is "bad" because coverage reports are missing entirely.
    if missing_files:
        changes.extend([Change(path=path, deleted=True) for path in missing_files])

    # [new] [~~diff~~] == new reports
    if new_files:
        changes.extend([Change(path=path, new=True) for path in new_files])

    return changes


def get_totals_from_list(lst) -> ReportTotals:
    """
    takes list of coverage values and returns a <ReportTotals>
    on the list
    IN [1,0,"1/2"] => OUT ReportTotals(hits=1, misses=1, partials=1)
    """
    lst = list(map(line_type, lst))
    return ReportTotals(hits=lst.count(0), misses=lst.count(1), partials=lst.count(2))


def iter_changed_lines(
    base_report_file, head_report_file, diff=None, yield_line_numbers=True
) -> Iterator[Union[int, Tuple[Any, Any]]]:
    """
    streams line numbers that changed as integers > 0
    """
    if not diff or diff["type"] == "modified":
        offsets, skip_lines, removed_lines = (
            get_segment_offsets(diff["segments"]) if diff else (None, None, None)
        )
        base_ln = 0
        base_report_file_eof = (
            base_report_file.eof if base_report_file is not None else 0
        )
        for ln in range(
            1,
            max(
                (
                    base_report_file_eof,
                    base_report_file_eof
                    + len(skip_lines or [])
                    - len(removed_lines or []),
                    head_report_file.eof,
                )
            )
            + 1,
        ):
            if offsets:
                base_ln += 1
                _offset = offsets.get(ln)
                if _offset is not None:
                    base_ln += _offset

            if not skip_lines or ln not in skip_lines:
                base_line = (
                    base_report_file.get(base_ln or ln)
                    if base_report_file is not None
                    else None
                )
                head_line = head_report_file.get(ln)
                # if a base line exist we can compare against
                if base_line:
                    if head_line:
                        # we have a head line
                        if line_has_changed(base_line, head_line):
                            # unexpected: coverage data changed
                            yield (
                                ln
                                if yield_line_numbers
                                else (
                                    base_line.coverage,
                                    head_line.coverage,
                                )
                            )
                        # coverage data remains the same
                    else:
                        # unexpected: coverage data disappeared
                        yield ln if yield_line_numbers else (base_line.coverage, None)

                elif head_line:
                    # unexpected: new coverage data
                    yield ln if yield_line_numbers else (None, head_line.coverage)


def line_has_changed(before, after) -> bool:
    # coverage changed
    return line_type(before.coverage) != line_type(after.coverage)
