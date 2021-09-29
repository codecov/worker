import pytest
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.reports.types import ReportTotals

from services.comparison.changes import Change, diff_totals, get_changes


class TestDiffTotals(object):
    @pytest.mark.parametrize(
        "base, head, absolute, res",
        [
            (ReportTotals(lines=1), None, None, False),
            (ReportTotals(lines=1), ReportTotals(lines=1), None, None),
            (None, ReportTotals(lines=1), None, True),
            (
                ReportTotals(lines=1, coverage=1),
                ReportTotals(lines=2, coverage=2),
                None,
                ReportTotals(lines=1, coverage=1),
            ),
            (
                ReportTotals(lines=2, coverage=3),
                ReportTotals(lines=1, coverage=4),
                None,
                ReportTotals(lines=-1, coverage=1),
            ),
            (
                ReportTotals(lines=2, coverage=5),
                ReportTotals(files=1, coverage=6),
                None,
                ReportTotals(files=1, lines=-2, coverage=1),
            ),
            (
                ReportTotals(coverage=15),
                ReportTotals(coverage=14),
                None,
                ReportTotals(coverage=-1),
            ),
            (
                ReportTotals(coverage=15),
                ReportTotals(coverage=14),
                ReportTotals(coverage=None),
                ReportTotals(coverage=-1),
            ),
        ],
    )
    def test_diff_totals(self, base, head, absolute, res):
        assert diff_totals(base, head, absolute) == res


class TestChanges(object):
    def test_get_changes(self):
        json_diff = {
            "files": {
                "modified.py": {
                    "before": None,
                    "segments": [
                        {
                            "header": ["20", "8", "20", "8"],
                            "lines": [
                                "     return k * k",
                                " ",
                                " ",
                                "-def k(l):",
                                "-    return 2 * l",
                                "+def k(var):",
                                "+    return 2 * var",
                                " ",
                                " ",
                                " def sample_function():",
                            ],
                        }
                    ],
                    "stats": {"added": 2, "removed": 2},
                    "type": "modified",
                },
                "renamed.py": {
                    "before": "old_renamed.py",
                    "segments": [],
                    "stats": {"added": 0, "removed": 0},
                    "type": "modified",
                },
                "renamed_with_changes.py": {
                    "before": "old_renamed_with_changes.py",
                    "segments": [],
                    "stats": {"added": 0, "removed": 0},
                    "type": "modified",
                },
                "added.py": {
                    "before": None,
                    "segments": [
                        {
                            "header": ["0", "0", "1", ""],
                            "lines": ["+This is an explanation"],
                        }
                    ],
                    "stats": {"added": 1, "removed": 0},
                    "type": "new",
                },
                "added_unnacounted.py": {
                    "before": None,
                    "segments": [
                        {
                            "header": ["50", "0", "50", "1"],
                            "lines": ["+This is an explanation"],
                        }
                    ],
                    "stats": {"added": 1, "removed": 0},
                    "type": "modified",
                },
                "deleted.py": {
                    "before": "tests/test_sample.py",
                    "stats": {"added": 0, "removed": 0},
                    "type": "deleted",
                },
            }
        }

        first_report = Report()
        second_report = Report()
        # DELETED FILE
        first_deleted_file = ReportFile("deleted.py")
        first_deleted_file.append(10, ReportLine.create(coverage=1))
        first_deleted_file.append(12, ReportLine.create(coverage=0))
        first_report.append(first_deleted_file)
        # ADDED FILE
        second_added_file = ReportFile("added.py")
        second_added_file.append(99, ReportLine.create(coverage=1))
        second_added_file.append(101, ReportLine.create(coverage=0))
        second_report.append(second_added_file)
        # ADDED FILE BUT UNNACOUNTED FOR
        second_added_file_unnaccounted_for = ReportFile("added_unnacounted.py")
        second_added_file_unnaccounted_for.append(99, ReportLine.create(coverage=1))
        second_added_file_unnaccounted_for.append(101, ReportLine.create(coverage=0))
        second_report.append(second_added_file_unnaccounted_for)
        # MODIFIED FILE
        first_modified_file = ReportFile("modified.py")
        first_modified_file.append(17, ReportLine.create(coverage=1))
        first_modified_file.append(18, ReportLine.create(coverage=1))
        first_modified_file.append(19, ReportLine.create(coverage=1))
        first_modified_file.append(20, ReportLine.create(coverage=0))
        first_modified_file.append(21, ReportLine.create(coverage=1))
        first_modified_file.append(22, ReportLine.create(coverage=1))
        first_modified_file.append(23, ReportLine.create(coverage=1))
        first_report.append(first_modified_file)
        second_modified_file = ReportFile("modified.py")
        second_modified_file.append(18, ReportLine.create(coverage=1))
        second_modified_file.append(19, ReportLine.create(coverage=0))
        second_modified_file.append(20, ReportLine.create(coverage=0))
        second_modified_file.append(21, ReportLine.create(coverage=1))
        second_modified_file.append(22, ReportLine.create(coverage=0))
        second_modified_file.append(23, ReportLine.create(coverage=0))
        second_report.append(second_modified_file)
        # RENAMED WITHOUT CHANGES
        first_renamed_without_changes_file = ReportFile("old_renamed.py")
        first_renamed_without_changes_file.append(1, ReportLine.create(coverage=1))
        first_renamed_without_changes_file.append(2, ReportLine.create(coverage=1))
        first_renamed_without_changes_file.append(3, ReportLine.create(coverage=0))
        first_renamed_without_changes_file.append(4, ReportLine.create(coverage=1))
        first_renamed_without_changes_file.append(5, ReportLine.create(coverage=0))
        first_report.append(first_renamed_without_changes_file)
        second_renamed_without_changes_file = ReportFile("renamed.py")
        second_renamed_without_changes_file.append(1, ReportLine.create(coverage=1))
        second_renamed_without_changes_file.append(2, ReportLine.create(coverage=1))
        second_renamed_without_changes_file.append(3, ReportLine.create(coverage=0))
        second_renamed_without_changes_file.append(4, ReportLine.create(coverage=1))
        second_renamed_without_changes_file.append(5, ReportLine.create(coverage=0))
        second_report.append(second_renamed_without_changes_file)
        # RENAMED WITH COVERAGE CHANGES FILE
        first_renamed_file = ReportFile("old_renamed_with_changes.py")
        first_renamed_file.append(2, ReportLine.create(coverage=1))
        first_renamed_file.append(3, ReportLine.create(coverage=1))
        first_renamed_file.append(5, ReportLine.create(coverage=0))
        first_renamed_file.append(8, ReportLine.create(coverage=1))
        first_renamed_file.append(13, ReportLine.create(coverage=1))
        first_report.append(first_renamed_file)
        second_renamed_file = ReportFile("renamed_with_changes.py")
        second_renamed_file.append(5, ReportLine.create(coverage=1))
        second_renamed_file.append(8, ReportLine.create(coverage=0))
        second_renamed_file.append(13, ReportLine.create(coverage=1))
        second_renamed_file.append(21, ReportLine.create(coverage=1))
        second_renamed_file.append(34, ReportLine.create(coverage=0))
        second_report.append(second_renamed_file)
        # UNRELATED FILE
        first_unrelated_file = ReportFile("unrelated.py")
        first_unrelated_file.append(1, ReportLine.create(coverage=1))
        first_unrelated_file.append(2, ReportLine.create(coverage=1))
        first_unrelated_file.append(4, ReportLine.create(coverage=1))
        first_unrelated_file.append(16, ReportLine.create(coverage=0))
        first_unrelated_file.append(256, ReportLine.create(coverage=1))
        first_unrelated_file.append(65556, ReportLine.create(coverage=1))
        first_report.append(first_unrelated_file)
        second_unrelated_file = ReportFile("unrelated.py")
        second_unrelated_file.append(2, ReportLine.create(coverage=1))
        second_unrelated_file.append(4, ReportLine.create(coverage=0))
        second_unrelated_file.append(8, ReportLine.create(coverage=0))
        second_unrelated_file.append(16, ReportLine.create(coverage=1))
        second_unrelated_file.append(32, ReportLine.create(coverage=0))
        second_report.append(second_unrelated_file)
        res = get_changes(first_report, second_report, json_diff)
        for r in res:
            print(r)
        expected_result = [
            Change(
                path="modified.py",
                new=False,
                deleted=False,
                in_diff=True,
                old_path=None,
                totals=ReportTotals(
                    files=0,
                    lines=0,
                    hits=-3,
                    misses=2,
                    partials=0,
                    coverage=-35.714290000000005,
                    branches=0,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=0,
                    complexity_total=0,
                    diff=0,
                ),
            ),
            Change(
                path="renamed_with_changes.py",
                new=False,
                deleted=False,
                in_diff=True,
                old_path="old_renamed_with_changes.py",
                totals=ReportTotals(
                    files=0,
                    lines=0,
                    hits=-1,
                    misses=1,
                    partials=0,
                    coverage=-20.0,
                    branches=0,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=0,
                    complexity_total=0,
                    diff=0,
                ),
            ),
            Change(
                path="unrelated.py",
                new=False,
                deleted=False,
                in_diff=False,
                old_path=None,
                totals=ReportTotals(
                    files=0,
                    lines=0,
                    hits=-3,
                    misses=2,
                    partials=0,
                    coverage=-43.333330000000004,
                    branches=0,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=0,
                    complexity_total=0,
                    diff=0,
                ),
            ),
            Change(
                path="added_unnacounted.py",
                new=True,
                deleted=False,
                in_diff=None,
                old_path=None,
                totals=None,
            ),
        ]
        for individual_result, individual_expected_result in zip(
            sorted(res, key=lambda x: x.path),
            sorted(expected_result, key=lambda x: x.path),
        ):
            assert individual_result == individual_expected_result
        assert sorted(res, key=lambda x: x.path) == sorted(
            expected_result, key=lambda x: x.path
        )

    def test_get_changes_missing_file(self):
        json_diff = {"files": {"a": {"before": "missing_file"}}}
        first_report_file = ReportFile("missing_file")
        first_report_file.append(18, ReportLine.create(coverage=1))
        first_report = Report()
        second_report = Report()
        second_report.append(first_report_file)
        res = get_changes(first_report, second_report, json_diff)
        for r in res:
            print(r)
        assert res == [
            Change(
                path="missing_file",
                new=True,
                deleted=False,
                in_diff=None,
                old_path=None,
                totals=None,
            )
        ]
