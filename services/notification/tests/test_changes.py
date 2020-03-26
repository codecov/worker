from services.notification.changes import get_changes, Change
from covreports.reports.types import ReportTotals
from covreports.reports.resources import Report, ReportFile, ReportLine


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
        first_deleted_file.append(10, ReportLine(coverage=1))
        first_deleted_file.append(12, ReportLine(coverage=0))
        first_report.append(first_deleted_file)
        # ADDED FILE
        second_added_file = ReportFile("added.py")
        second_added_file.append(99, ReportLine(coverage=1))
        second_added_file.append(101, ReportLine(coverage=0))
        second_report.append(second_added_file)
        # MODIFIED FILE
        first_modified_file = ReportFile("modified.py")
        first_modified_file.append(17, ReportLine(coverage=1))
        first_modified_file.append(18, ReportLine(coverage=1))
        first_modified_file.append(19, ReportLine(coverage=1))
        first_modified_file.append(20, ReportLine(coverage=0))
        first_modified_file.append(21, ReportLine(coverage=1))
        first_modified_file.append(22, ReportLine(coverage=1))
        first_report.append(first_modified_file)
        second_modified_file = ReportFile("modified.py")
        second_modified_file.append(18, ReportLine(coverage=1))
        second_modified_file.append(19, ReportLine(coverage=0))
        second_modified_file.append(20, ReportLine(coverage=0))
        second_modified_file.append(21, ReportLine(coverage=1))
        second_modified_file.append(22, ReportLine(coverage=0))
        second_report.append(second_modified_file)
        # RENAMED WITHOUT CHANGES
        first_renamed_without_changes_file = ReportFile("old_renamed.py")
        first_renamed_without_changes_file.append(1, ReportLine(coverage=1))
        first_renamed_without_changes_file.append(2, ReportLine(coverage=1))
        first_renamed_without_changes_file.append(3, ReportLine(coverage=0))
        first_renamed_without_changes_file.append(4, ReportLine(coverage=1))
        first_renamed_without_changes_file.append(5, ReportLine(coverage=0))
        first_report.append(first_renamed_without_changes_file)
        second_renamed_without_changes_file = ReportFile("renamed.py")
        second_renamed_without_changes_file.append(1, ReportLine(coverage=1))
        second_renamed_without_changes_file.append(2, ReportLine(coverage=1))
        second_renamed_without_changes_file.append(3, ReportLine(coverage=0))
        second_renamed_without_changes_file.append(4, ReportLine(coverage=1))
        second_renamed_without_changes_file.append(5, ReportLine(coverage=0))
        second_report.append(second_renamed_without_changes_file)
        # RENAMED WITH COVERAGE CHANGES FILE
        first_renamed_file = ReportFile("old_renamed_with_changes.py")
        first_renamed_file.append(2, ReportLine(coverage=1))
        first_renamed_file.append(3, ReportLine(coverage=1))
        first_renamed_file.append(5, ReportLine(coverage=0))
        first_renamed_file.append(8, ReportLine(coverage=1))
        first_renamed_file.append(13, ReportLine(coverage=1))
        first_report.append(first_renamed_file)
        second_renamed_file = ReportFile("renamed_with_changes.py")
        second_renamed_file.append(5, ReportLine(coverage=1))
        second_renamed_file.append(8, ReportLine(coverage=0))
        second_renamed_file.append(13, ReportLine(coverage=1))
        second_renamed_file.append(21, ReportLine(coverage=1))
        second_renamed_file.append(34, ReportLine(coverage=0))
        second_report.append(second_renamed_file)
        # UNRELATED FILE
        first_unrelated_file = ReportFile("unrelated.py")
        first_unrelated_file.append(1, ReportLine(coverage=1))
        first_unrelated_file.append(2, ReportLine(coverage=1))
        first_unrelated_file.append(4, ReportLine(coverage=1))
        first_unrelated_file.append(16, ReportLine(coverage=0))
        first_unrelated_file.append(256, ReportLine(coverage=1))
        first_unrelated_file.append(65556, ReportLine(coverage=1))
        first_report.append(first_unrelated_file)
        second_unrelated_file = ReportFile("unrelated.py")
        second_unrelated_file.append(2, ReportLine(coverage=1))
        second_unrelated_file.append(4, ReportLine(coverage=0))
        second_unrelated_file.append(8, ReportLine(coverage=0))
        second_unrelated_file.append(16, ReportLine(coverage=1))
        second_unrelated_file.append(32, ReportLine(coverage=0))
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
                    hits=-2,
                    misses=1,
                    partials=0,
                    coverage=-23.333330000000004,
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
                path="added.py",
                new=True,
                deleted=False,
                in_diff=None,
                old_path=None,
                totals=None,
            ),
        ]
        assert sorted(res, key=lambda x: x.path) == sorted(
            expected_result, key=lambda x: x.path
        )
