from copy import deepcopy
from unittest.mock import Mock
from urllib.parse import quote_plus

import pytest
from shared.reports.readonly import ReadOnlyReport
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.torngit.exceptions import TorngitClientGeneralError, TorngitError
from shared.torngit.status import Status
from shared.yaml.user_yaml import UserYaml

from services.decoration import Decoration
from services.notification.notifiers.base import NotificationResult
from services.notification.notifiers.checks import (
    ChangesChecksNotifier,
    PatchChecksNotifier,
    ProjectChecksNotifier,
)
from services.notification.notifiers.checks.base import ChecksNotifier
from services.notification.notifiers.checks.checks_with_fallback import (
    ChecksWithFallback,
)
from services.notification.notifiers.status import PatchStatusNotifier


@pytest.fixture
def mock_repo_provider(mock_repo_provider):
    compare_result = {
        "diff": {
            "files": {
                "file_1.go": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["5", "8", "5", "9"],
                            "lines": [
                                " Overview",
                                " --------",
                                " ",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "+",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                " ",
                                " .. code-block:: shell-session",
                                " ",
                            ],
                        },
                        {
                            "header": ["46", "12", "47", "19"],
                            "lines": [
                                " ",
                                " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                " ",
                                "-We highly suggest adding `source` to your ``.coveragerc`` which solves a number of issues collecting coverage.",
                                "+We highly suggest adding ``source`` to your ``.coveragerc``, which solves a number of issues collecting coverage.",
                                " ",
                                " .. code-block:: ini",
                                " ",
                                "    [run]",
                                "    source=your_package_name",
                                "+   ",
                                "+If there are multiple sources, you instead should add ``include`` to your ``.coveragerc``",
                                "+",
                                "+.. code-block:: ini",
                                "+",
                                "+   [run]",
                                "+   include=your_package_name/*",
                                " ",
                                " unittests",
                                " ---------",
                            ],
                        },
                        {
                            "header": ["150", "5", "158", "4"],
                            "lines": [
                                " * Twitter: `@codecov <https://twitter.com/codecov>`_.",
                                " * Email: `hello@codecov.io <hello@codecov.io>`_.",
                                " ",
                                "-We are happy to help if you have any questions. Please contact email our Support at [support@codecov.io](mailto:support@codecov.io)",
                                "-",
                                "+We are happy to help if you have any questions. Please contact email our Support at `support@codecov.io <mailto:support@codecov.io>`_.",
                            ],
                        },
                    ],
                    "stats": {"added": 11, "removed": 4},
                }
            }
        },
        "commits": [
            {
                "commitid": "b92edba44fdd29fcc506317cc3ddeae1a723dd08",
                "message": "Update README.rst",
                "timestamp": "2018-07-09T23:51:16Z",
                "author": {
                    "id": 8398772,
                    "username": "jerrode",
                    "name": "Jerrod",
                    "email": "jerrod@fundersclub.com",
                },
            },
            {
                "commitid": "6ae5f1795a441884ed2847bb31154814ac01ef38",
                "message": "Update README.rst",
                "timestamp": "2018-04-26T08:35:58Z",
                "author": {
                    "id": 11602092,
                    "username": "TomPed",
                    "name": "Thomas Pedbereznak",
                    "email": "tom@tomped.com",
                },
            },
        ],
    }
    mock_repo_provider.get_compare.return_value = compare_result
    return mock_repo_provider


@pytest.fixture
def comparison_with_multiple_changes(sample_comparison):
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
    # MODIFIED FILE
    first_modified_file = ReportFile("modified.py")
    first_modified_file.append(17, ReportLine.create(coverage=1))
    first_modified_file.append(18, ReportLine.create(coverage=1))
    first_modified_file.append(19, ReportLine.create(coverage=1))
    first_modified_file.append(20, ReportLine.create(coverage=0))
    first_modified_file.append(21, ReportLine.create(coverage=1))
    first_modified_file.append(22, ReportLine.create(coverage=1))
    first_modified_file.append(23, ReportLine.create(coverage=1))
    first_modified_file.append(24, ReportLine.create(coverage=1))
    first_report.append(first_modified_file)
    second_modified_file = ReportFile("modified.py")
    second_modified_file.append(18, ReportLine.create(coverage=1))
    second_modified_file.append(19, ReportLine.create(coverage=0))
    second_modified_file.append(20, ReportLine.create(coverage=0))
    second_modified_file.append(21, ReportLine.create(coverage=1))
    second_modified_file.append(22, ReportLine.create(coverage=0))
    second_modified_file.append(23, ReportLine.create(coverage=0))
    second_modified_file.append(24, ReportLine.create(coverage=1))
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
    sample_comparison.project_coverage_base.report = ReadOnlyReport.create_from_report(
        first_report
    )
    sample_comparison.head.report = ReadOnlyReport.create_from_report(second_report)
    return sample_comparison


@pytest.fixture
def multiple_diff_changes():
    return {
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


class TestChecksWithFallback(object):
    def test_checks_403_failure(self, sample_comparison, mocker, mock_repo_provider):
        mock_repo_provider.create_check_run = Mock(
            side_effect=TorngitClientGeneralError(
                403, response_data="No Access", message="No Access"
            )
        )

        checks_notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        status_notifier = mocker.MagicMock(
            PatchStatusNotifier(
                repository=sample_comparison.head.commit.repository,
                title="title",
                notifier_yaml_settings={"flags": ["flagone"]},
                notifier_site_settings=True,
                current_yaml=UserYaml({}),
                repository_service=mock_repo_provider,
            )
        )
        status_notifier.notify.return_value = "success"
        fallback_notifier = ChecksWithFallback(
            checks_notifier=checks_notifier, status_notifier=status_notifier
        )
        assert fallback_notifier.name == "checks-patch-with-fallback"
        assert fallback_notifier.title == "title"
        assert fallback_notifier.is_enabled() == True
        assert fallback_notifier.notification_type.value == "checks_patch"
        assert fallback_notifier.decoration_type is None

        res = fallback_notifier.notify(sample_comparison)
        fallback_notifier.store_results(sample_comparison, res)
        assert status_notifier.notify.call_count == 1
        assert fallback_notifier.name == "checks-patch-with-fallback"
        assert fallback_notifier.title == "title"
        assert fallback_notifier.is_enabled() == True
        assert fallback_notifier.notification_type.value == "checks_patch"
        assert fallback_notifier.decoration_type is None
        assert res == "success"

    def test_checks_failure(self, sample_comparison, mocker, mock_repo_provider):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.create_check_run = Mock(
            side_effect=TorngitClientGeneralError(
                409, response_data="No Access", message="No Access"
            )
        )

        checks_notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        status_notifier = mocker.MagicMock(
            PatchStatusNotifier(
                repository=sample_comparison.head.commit.repository,
                title="title",
                notifier_yaml_settings={"flags": ["flagone"]},
                notifier_site_settings=True,
                current_yaml=UserYaml({}),
                repository_service=mock_repo_provider,
            )
        )
        status_notifier.notify.return_value = "success"
        fallback_notifier = ChecksWithFallback(
            checks_notifier=checks_notifier, status_notifier=status_notifier
        )
        assert fallback_notifier.name == "checks-patch-with-fallback"
        assert fallback_notifier.title == "title"
        assert fallback_notifier.is_enabled() == True
        assert fallback_notifier.notification_type.value == "checks_patch"
        assert fallback_notifier.decoration_type is None

        res = fallback_notifier.notify(sample_comparison)
        assert res.notification_successful == False
        assert res.explanation == "client_side_error_provider"

        mock_repo_provider.create_check_run = Mock(side_effect=TorngitError())

        res = fallback_notifier.notify(sample_comparison)
        assert res.notification_successful == False
        assert res.explanation == "server_side_error_provider"

        mock_repo_provider.create_check_run.return_value = 1234
        mock_repo_provider.update_check_run = Mock(side_effect=TorngitError())
        res = fallback_notifier.notify(sample_comparison)
        assert res.notification_successful == False
        assert res.explanation == "server_side_error_provider"

    def test_checks_no_pull(self, sample_comparison_without_pull, mocker):
        comparison = sample_comparison_without_pull
        checks_notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        status_notifier = mocker.MagicMock(
            PatchStatusNotifier(
                repository=comparison.head.commit.repository,
                title="title",
                notifier_yaml_settings={"flags": ["flagone"]},
                notifier_site_settings=True,
                current_yaml=UserYaml({}),
                repository_service=None,
            )
        )
        status_notifier.notify.return_value = "success"
        fallback_notifier = ChecksWithFallback(
            checks_notifier=checks_notifier, status_notifier=status_notifier
        )
        result = fallback_notifier.notify(sample_comparison_without_pull)
        assert result == "success"
        assert status_notifier.notify.call_count == 1

    def test_notify_pull_request_not_in_provider(
        self, dbsession, sample_comparison_database_pull_without_provider, mocker
    ):
        comparison = sample_comparison_database_pull_without_provider
        checks_notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        status_notifier = mocker.MagicMock(
            PatchStatusNotifier(
                repository=comparison.head.commit.repository,
                title="title",
                notifier_yaml_settings={"flags": ["flagone"]},
                notifier_site_settings=True,
                current_yaml=UserYaml({}),
                repository_service=None,
            )
        )
        status_notifier.notify.return_value = "success"
        fallback_notifier = ChecksWithFallback(
            checks_notifier=checks_notifier, status_notifier=status_notifier
        )
        result = fallback_notifier.notify(comparison)
        assert result == "success"
        assert status_notifier.notify.call_count == 1

    def test_notify_closed_pull_request(self, dbsession, sample_comparison, mocker):
        sample_comparison.pull.state = "closed"

        checks_notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        status_notifier = mocker.MagicMock(
            PatchStatusNotifier(
                repository=sample_comparison.head.commit.repository,
                title="title",
                notifier_yaml_settings={"flags": ["flagone"]},
                notifier_site_settings=True,
                current_yaml=UserYaml({}),
                repository_service=None,
            )
        )
        status_notifier.notify.return_value = "success"
        fallback_notifier = ChecksWithFallback(
            checks_notifier=checks_notifier, status_notifier=status_notifier
        )
        result = fallback_notifier.notify(sample_comparison)
        assert result == "success"
        assert status_notifier.notify.call_count == 1


class TestBaseChecksNotifier(object):
    def test_create_annotations_single_segment(self, sample_comparison):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        diff = {
            "files": {
                "file_1.go": {
                    "type": "modified",
                    "before": "None",
                    "segments": [
                        {
                            "header": ["5", "8", "5", "9"],
                            "lines": [
                                " Overview",
                                " --------",
                                " ",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "+",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                " ",
                                " .. code-block:: shell-session",
                                " ",
                            ],
                        }
                    ],
                    "totals": True,
                }
            }
        }
        expected_annotations = [
            {
                "path": "file_1.go",
                "start_line": 10,
                "end_line": 10,
                "annotation_level": "warning",
                "message": "Added line #L10 was not covered by tests",
            }
        ]
        annotations = notifier.create_annotations(sample_comparison, diff)
        assert expected_annotations == annotations

    def test_create_annotations_multiple_segments(self, sample_comparison):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        diff = {
            "files": {
                "file_1.go": {
                    "type": "modified",
                    "before": "None",
                    "segments": [
                        {
                            "header": ["1", "1", "1", "1"],
                            "lines": [
                                " ",
                                "+ You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                " ",
                                "-We highly suggest adding `source` to your ``.coveragerc`` which solves a number of issues collecting coverage.",
                                "+We highly suggest adding ``source`` to your ``.coveragerc``, which solves a number of issues collecting coverage.",
                                " ---------",
                            ],
                        },
                        {
                            "header": ["5", "8", "5", "9"],
                            "lines": [
                                " Overview",
                                " --------",
                                " ",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "+",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                " ",
                                " .. code-block:: shell-session",
                                " ",
                            ],
                        },
                        {
                            "header": ["150", "5", "158", "4"],
                            "lines": [
                                " * Twitter: `@codecov <https://twitter.com/codecov>`_.",
                                " * Email: `hello@codecov.io <hello@codecov.io>`_.",
                                " ",
                                "-We are happy to help if you have any questions. Please contact email our Support at [support@codecov.io](mailto:support@codecov.io)",
                                "-",
                                "+We are happy to help if you have any questions. Please contact email our Support at `support@codecov.io <mailto:support@codecov.io>`_.",
                            ],
                        },
                    ],
                    "totals": True,
                }
            }
        }
        expected_annotations = [
            {
                "path": "file_1.go",
                "start_line": 2,
                "end_line": 2,
                "annotation_level": "warning",
                "message": "Added line #L2 was not covered by tests",
            },
            {
                "path": "file_1.go",
                "start_line": 10,
                "end_line": 10,
                "annotation_level": "warning",
                "message": "Added line #L10 was not covered by tests",
            },
        ]
        annotations = notifier.create_annotations(sample_comparison, diff)
        assert expected_annotations == annotations

    def test_get_lines_to_annotate_no_consecutive_lines(self, sample_comparison):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        files_with_change = [
            {
                "type": "modified",
                "path": "file_1.go",
                "additions": [
                    {"head_line": 1},
                    {"head_line": 2},
                    {"head_line": 3},
                    {"head_line": 5},
                    {"head_line": 6},
                    {"head_line": 8},
                ],
            }
        ]
        expected_result = [
            {
                "type": "new_line",
                "line": 2,
                "coverage": 0,
                "path": "file_1.go",
                "end_line": 2,
            },
            {
                "type": "new_line",
                "line": 6,
                "coverage": 0,
                "path": "file_1.go",
                "end_line": 6,
            },
        ]
        result = notifier.get_lines_to_annotate(sample_comparison, files_with_change)
        assert expected_result == result

    def test_get_lines_to_annotate_consecutive_lines(self, sample_comparison):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        report = Report()
        first_deleted_file = ReportFile("file_1.go")
        first_deleted_file.append(1, ReportLine.create(coverage=0))
        first_deleted_file.append(2, ReportLine.create(coverage=0))
        first_deleted_file.append(3, ReportLine.create(coverage=0))
        first_deleted_file.append(5, ReportLine.create(coverage=0))
        report.append(first_deleted_file)
        sample_comparison.head.report = report
        files_with_change = [
            {
                "type": "modified",
                "path": "file_1.go",
                "additions": [
                    {"head_line": 1},
                    {"head_line": 2},
                    {"head_line": 3},
                    {"head_line": 5},
                    {"head_line": 6},
                    {"head_line": 8},
                ],
            }
        ]
        expected_result = [
            {
                "type": "new_line",
                "line": 1,
                "coverage": 0,
                "path": "file_1.go",
                "end_line": 3,
            },
            {
                "type": "new_line",
                "line": 5,
                "coverage": 0,
                "path": "file_1.go",
                "end_line": 5,
            },
        ]
        result = notifier.get_lines_to_annotate(sample_comparison, files_with_change)
        assert expected_result == result


class TestPatchChecksNotifier(object):
    def test_paginate_annotations(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        sample_array = list(range(1, 61, 1))
        expected_result = [list(range(1, 51, 1)), list(range(51, 61, 1))]
        result = list(notifier.paginate_annotations(sample_array))
        assert expected_result == result

    def test_build_flag_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "66.67% of diff hit (target 50.00%)",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_flag_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n66.67% of diff hit (target 50.00%)",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"] = {
            "codecov_url": "test.example.br",
            "codecov_dashboard_url": "test.example.br",
        }
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_upgrade_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nThe author of this PR, codecov-test-user, is not an activated member of this organization on Codecov.\nPlease [activate this user on Codecov](test.example.br/members/gh/test_build_upgrade_payload) to display a detailed status check.\nCoverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.\nPlease don't hesitate to email us at support@codecov.io with any questions.",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_default_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "66.67% of diff hit (target 50.00%)",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n66.67% of diff hit (target 50.00%)",
                "annotations": [
                    {
                        "path": "file_1.go",
                        "start_line": 10,
                        "end_line": 10,
                        "annotation_level": "warning",
                        "message": "Added line #L10 was not covered by tests",
                    }
                ],
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result["output"]["summary"] == result["output"]["summary"]
        assert expected_result == result

    def test_build_payload_target_coverage_failure(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": "70%", "paths": ["pathone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "failure",
            "output": {
                "title": "66.67% of diff hit (target 70.00%)",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_target_coverage_failure/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n66.67% of diff hit (target 70.00%)",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_without_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "No report found to compare against",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_without_base_report/{sample_comparison_without_base_report.head.commit.repository.name}/pull/{sample_comparison_without_base_report.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nNo report found to compare against",
                "annotations": [
                    {
                        "path": "file_1.go",
                        "start_line": 10,
                        "end_line": 10,
                        "annotation_level": "warning",
                        "message": "Added line #L10 was not covered by tests",
                    }
                ],
            },
        }
        result = notifier.build_payload(comparison)
        assert expected_result == result

    def test_build_payload_target_coverage_failure_witinh_threshold(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        third_file = ReportFile("file_3.c")
        third_file.append(100, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(101, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(102, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(103, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        sample_comparison.project_coverage_base.report.append(third_file)
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={"threshold": "5"},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "66.67% of diff hit (within 5.00% threshold of 70.00%)",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_target_coverage_failure_witinh_threshold/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n66.67% of diff hit (within 5.00% threshold of 70.00%)",
                "annotations": [
                    {
                        "path": "file_1.go",
                        "start_line": 10,
                        "end_line": 10,
                        "annotation_level": "warning",
                        "message": "Added line #L10 was not covered by tests",
                    }
                ],
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result["state"] == result["state"]
        assert expected_result["output"]["summary"] == result["output"]["summary"]
        assert expected_result["output"] == result["output"]
        assert expected_result == result

    def test_build_payload_with_multiple_changes(
        self,
        comparison_with_multiple_changes,
        mock_repo_provider,
        mock_configuration,
        multiple_diff_changes,
    ):
        json_diff = multiple_diff_changes
        original_value = deepcopy(multiple_diff_changes)
        mock_repo_provider.get_compare.return_value = {"diff": json_diff}

        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "failure",
            "output": {
                "title": "50.00% of diff hit (target 76.92%)",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_with_multiple_changes/{comparison_with_multiple_changes.head.commit.repository.name}/pull/{comparison_with_multiple_changes.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n50.00% of diff hit (target 76.92%)",
                "annotations": [
                    {
                        "path": "modified.py",
                        "start_line": 23,
                        "end_line": 23,
                        "annotation_level": "warning",
                        "message": "Added line #L23 was not covered by tests",
                    }
                ],
            },
        }
        result = notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result["state"] == result["state"]
        assert expected_result["output"] == result["output"]
        assert expected_result == result
        # assert that the value of diff was not changed
        for filename in original_value["files"]:
            assert original_value["files"][filename].get(
                "segments"
            ) == multiple_diff_changes["files"][filename].get("segments")

    def test_build_payload_no_diff(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_compare.return_value = {
            "diff": {
                "files": {
                    "file_1.go": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["15", "8", "15", "9"],
                                "lines": [
                                    " Overview",
                                    " --------",
                                    " ",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "+",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    " ",
                                    " .. code-block:: shell-session",
                                    " ",
                                ],
                            }
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        assert notifier.is_enabled()
        notifier.name
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": f"Coverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_no_diff/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nCoverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert notifier.notification_type.value == "checks_patch"
        assert expected_result == result

    def test_send_notification(self, sample_comparison, mocker, mock_repo_provider):
        comparison = sample_comparison
        payload = {
            "state": "success",
            "output": {"title": "Codecov Report", "summary": "Summary"},
            "url": "https://app.codecov.io/gh/codecov/worker/compare/100?src=pr&el=continue&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term=codecov",
        }
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        result = notifier.send_notification(sample_comparison, payload)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {"title": "Codecov Report", "summary": "Summary"},
            "url": "https://app.codecov.io/gh/codecov/worker/compare/100?src=pr&el=continue&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term=codecov",
        }

    def test_send_notification_annotations_paginations(
        self, sample_comparison, mocker, mock_repo_provider
    ):
        comparison = sample_comparison
        payload = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": "Summary",
                "annotations": list(range(1, 61, 1)),
            },
        }
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_calls = [
            {
                "output": {
                    "title": "Codecov Report",
                    "summary": "Summary",
                    "annotations": list(range(1, 51, 1)),
                },
                "url": None,
            },
            {
                "output": {
                    "title": "Codecov Report",
                    "summary": "Summary",
                    "annotations": list(range(51, 61, 1)),
                },
                "url": None,
            },
        ]
        result = notifier.send_notification(sample_comparison, payload)
        assert result.notification_successful == True
        assert result.explanation is None
        calls = [call[1] for call in mock_repo_provider.update_check_run.call_args_list]
        assert expected_calls == calls
        assert mock_repo_provider.update_check_run.call_count == 2
        assert result.data_sent == {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": "Summary",
                "annotations": list(range(1, 61, 1)),
            },
        }

    def test_notify(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        payload = {
            "state": "success",
            "output": {"title": "Codecov Report", "summary": "Summary"},
        }
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["pathone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {
                "title": f"Coverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_notify/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nCoverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}",
            },
            "url": f"test.example.br/gh/test_notify/{sample_comparison.head.commit.repository.name}/pull/{comparison.pull.pullid}",
        }

    def test_notify_passing_empty_upload(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["pathone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.passing_empty_upload,
        )
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {
                "title": "Empty Upload",
                "summary": "Non-testable files changed.",
            },
            "url": f"test.example.br/gh/test_notify_passing_empty_upload/{sample_comparison.head.commit.repository.name}/pull/{comparison.pull.pullid}",
        }

    def test_notify_failing_empty_upload(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["pathone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.failing_empty_upload,
        )
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "failure",
            "output": {
                "title": "Empty Upload",
                "summary": "Testable files changed",
            },
            "url": f"test.example.br/gh/test_notify_failing_empty_upload/{sample_comparison.head.commit.repository.name}/pull/{comparison.pull.pullid}",
        }

    def test_notification_exception(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )

        # Test exception handling when there's a TorngitClientError
        mock_repo_provider.get_compare = Mock(
            side_effect=TorngitClientGeneralError(
                400, response_data="Error", message="Error"
            )
        )
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == False
        assert result.explanation == "client_side_error_provider"
        assert result.data_sent is None

        # Test exception handling when there's a TorngitError
        mock_repo_provider.get_compare = Mock(side_effect=TorngitError())
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == False
        assert result.explanation == "server_side_error_provider"
        assert result.data_sent is None

    def test_notification_exception_not_fit(self, sample_comparison, mocker):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        mocker.patch.object(
            ChecksNotifier, "can_we_set_this_status", return_value=False
        )
        result = notifier.notify(sample_comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "not_fit_criteria"
        assert result.data_sent is None
        assert result.data_received is None

    def test_notification_exception_preexisting_commit_status(
        self, sample_comparison, mocker, mock_repo_provider
    ):
        comparison = sample_comparison
        notifier = ProjectChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["file_1.go"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        mock_repo_provider.get_commit_statuses.return_value = Status(
            [
                {
                    "time": "2024-10-01T22:34:52Z",
                    "state": "success",
                    "description": "42.85% (+0.00%) compared to 36be7f3",
                    "context": "codecov/project/title",
                }
            ]
        )
        result = notifier.notify(sample_comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "preexisting_commit_status"
        assert result.data_sent is None
        assert result.data_received is None

    def test_checks_with_after_n_builds(self, sample_comparison, mocker):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["unit"]},
            notifier_site_settings=True,
            current_yaml=UserYaml(
                {
                    "coverage": {
                        "status": {"project": True, "patch": True, "changes": True}
                    },
                    "flag_management": {
                        "default_rules": {"carryforward": False},
                        "individual_flags": [
                            {
                                "name": "unit",
                                "statuses": [{"type": "patch"}],
                                "after_n_builds": 3,
                            },
                        ],
                    },
                }
            ),
            repository_service=None,
        )

        mocker.patch.object(ChecksNotifier, "can_we_set_this_status", return_value=True)
        result = notifier.notify(sample_comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "need_more_builds"
        assert result.data_sent is None
        assert result.data_received is None


class TestChangesChecksNotifier(object):
    def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "No indirect coverage changes found",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nNo indirect coverage changes found",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result
        assert notifier.notification_type.value == "checks_changes"

    def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"] = {
            "codecov_url": "test.example.br",
            "codecov_dashboard_url": "test.example.br",
        }
        notifier = ChangesChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_upgrade_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nThe author of this PR, codecov-test-user, is not an activated member of this organization on Codecov.\nPlease [activate this user on Codecov](test.example.br/members/gh/test_build_upgrade_payload) to display a detailed status check.\nCoverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.\nPlease don't hesitate to email us at support@codecov.io with any questions.",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_with_multiple_changes(
        self,
        comparison_with_multiple_changes,
        mock_repo_provider,
        mock_configuration,
        multiple_diff_changes,
    ):
        json_diff = multiple_diff_changes
        mock_repo_provider.get_compare.return_value = {"diff": json_diff}

        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesChecksNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "failure",
            "output": {
                "title": "3 files have indirect coverage changes not visible in diff",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_with_multiple_changes/{comparison_with_multiple_changes.head.commit.repository.name}/pull/{comparison_with_multiple_changes.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n3 files have indirect coverage changes not visible in diff",
            },
        }
        result = notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result == result

    def test_build_payload_without_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = ChangesChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Unable to determine changes, no report found at pull request base",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_without_base_report/{sample_comparison_without_base_report.head.commit.repository.name}/pull/{sample_comparison_without_base_report.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nUnable to determine changes, no report found at pull request base",
            },
        }
        result = notifier.build_payload(comparison)
        assert expected_result == result

    def test_build_failing_empty_upload_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"] = {
            "codecov_url": "test.example.br",
            "codecov_dashboard_url": "test.example.br",
        }
        notifier = ChangesChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.failing_empty_upload,
        )
        expected_result = {
            "state": "failure",
            "output": {
                "title": "Empty Upload",
                "summary": "Testable files changed",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result


class TestProjectChecksNotifier(object):
    def test_analytics_url(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "codecov.io"
        repo = sample_comparison.head.commit.repository
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        payload = {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "text": "\n".join(
                    [
                        f"## [Codecov](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1) Report",
                        f"> Merging [#{sample_comparison.pull.pullid}](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=desc) ({head_commit.commitid[:7]}) into [master](codecov.io/gh/test_build_default_payload/{repo.name}/commit/{sample_comparison.project_coverage_base.commit.commitid}?el=desc) ({base_commit.commitid[:7]}) will **increase** coverage by `10.00%`.",
                        "> The diff coverage is `66.67%`.",
                        "",
                        f"| [Files with missing lines](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
                        "|---|---|---|---|",
                        f"| [file\\_1.go](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
                        f"| [file\\_2.py](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_2.py#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
                        "",
                    ]
                ),
            },
        }
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"comment": {"layout": "files"}},
            repository_service=mock_repo_provider,
        )
        result = notifier.send_notification(sample_comparison, payload)
        expected_result = {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term={quote_plus(repo.owner.name)})\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "text": "\n".join(
                    [
                        f"## [Codecov](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term={quote_plus(repo.owner.name)}) Report",
                        f"> Merging [#{sample_comparison.pull.pullid}](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=desc&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term={quote_plus(repo.owner.name)}) ({head_commit.commitid[:7]}) into [master](codecov.io/gh/test_build_default_payload/{repo.name}/commit/{sample_comparison.project_coverage_base.commit.commitid}?el=desc&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term={quote_plus(repo.owner.name)}) ({base_commit.commitid[:7]}) will **increase** coverage by `10.00%`.",
                        "> The diff coverage is `66.67%`.",
                        "",
                        f"| [Files with missing lines](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term={quote_plus(repo.owner.name)}) | Coverage Δ | Complexity Δ | |",
                        "|---|---|---|---|",
                        f"| [file\\_1.go](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term={quote_plus(repo.owner.name)}#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
                        f"| [file\\_2.py](codecov.io/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_2.py&utm_medium=referral&utm_source=github&utm_content=checks&utm_campaign=pr+comments&utm_term={quote_plus(repo.owner.name)}#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
                        "",
                    ]
                ),
            },
        }
        assert expected_result["output"]["text"].split("\n") == result.data_sent[
            "output"
        ]["text"].split("\n")
        assert expected_result == result.data_sent

    def test_build_flag_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        result = notifier.build_payload(sample_comparison)
        base_commit = sample_comparison.project_coverage_base.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_flag_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            },
        }
        assert result == expected_result
        assert notifier.notification_type.value == "checks_project"

    def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"] = {
            "codecov_url": "test.example.br",
            "codecov_dashboard_url": "test.example.br",
        }
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_upgrade_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nThe author of this PR, codecov-test-user, is not an activated member of this organization on Codecov.\nPlease [activate this user on Codecov](test.example.br/members/gh/test_build_upgrade_payload) to display a detailed status check.\nCoverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.\nPlease don't hesitate to email us at support@codecov.io with any questions.",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_passing_empty_upload_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"] = {
            "codecov_url": "test.example.br",
            "codecov_dashboard_url": "test.example.br",
        }
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.passing_empty_upload,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Empty Upload",
                "summary": "Non-testable files changed.",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_default_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"comment": {"layout": "files"}},
            repository_service=mock_repo_provider,
        )
        result = notifier.build_payload(sample_comparison)
        repo = sample_comparison.head.commit.repository
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "text": "\n".join(
                    [
                        f"## [Codecov](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1) Report",
                        "Attention: Patch coverage is `66.66667%` with `1 line` in your changes missing coverage. Please review.",
                        f"> Project coverage is 60.00%. Comparing base [(`{base_commit.commitid[:7]}`)](test.example.br/gh/test_build_default_payload/{repo.name}/commit/{base_commit.commitid}?dropdown=coverage&el=desc) to head [(`{head_commit.commitid[:7]}`)](test.example.br/gh/test_build_default_payload/{repo.name}/commit/{head_commit.commitid}?dropdown=coverage&el=desc)."
                        f"",
                        "",
                        f"| [Files with missing lines](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=tree) | Patch % | Lines |",
                        "|---|---|---|",
                        f"| [file\\_1.go](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go#diff-ZmlsZV8xLmdv) | 66.67% | [1 Missing :warning: ](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree) |",
                        "",
                        f"| [Files with missing lines](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
                        "|---|---|---|---|",
                        f"| [file\\_1.go](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
                        "",
                        f"... and [1 file with indirect coverage changes](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}/indirect-changes?src=pr&el=tree-more)",
                        "",
                    ]
                ),
            },
        }
        assert expected_result["output"]["text"].split("\n") == result["output"][
            "text"
        ].split("\n")
        assert expected_result == result

    def test_build_default_payload_with_flags(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"comment": {"layout": "files, flags"}},
            repository_service=mock_repo_provider,
        )
        result = notifier.build_payload(sample_comparison)
        repo = sample_comparison.head.commit.repository
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "text": "\n".join(
                    [
                        f"## [Codecov](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1) Report",
                        "Attention: Patch coverage is `66.66667%` with `1 line` in your changes missing coverage. Please review.",
                        f"> Project coverage is 60.00%. Comparing base [(`{base_commit.commitid[:7]}`)](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/commit/{base_commit.commitid}?dropdown=coverage&el=desc) to head [(`{head_commit.commitid[:7]}`)](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/commit/{head_commit.commitid}?dropdown=coverage&el=desc)."
                        f"",
                        "",
                        f"| [Files with missing lines](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=tree) | Patch % | Lines |",
                        "|---|---|---|",
                        f"| [file\\_1.go](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go#diff-ZmlsZV8xLmdv) | 66.67% | [1 Missing :warning: ](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree) |",
                        "",
                        f"| [Files with missing lines](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
                        "|---|---|---|---|",
                        f"| [file\\_1.go](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
                        "",
                        f"... and [1 file with indirect coverage changes](test.example.br/gh/test_build_default_payload_with_flags/{repo.name}/pull/{sample_comparison.pull.pullid}/indirect-changes?src=pr&el=tree-more)",
                        "",
                    ]
                ),
            },
        }
        assert expected_result["output"]["text"].split("\n") == result["output"][
            "text"
        ].split("\n")
        assert expected_result == result

    def test_build_default_payload_with_flags_and_footer(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        test_name = "test_build_default_payload_with_flags_and_footer"
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"comment": {"layout": "files, flags, footer"}},
            repository_service=mock_repo_provider,
        )
        result = notifier.build_payload(sample_comparison)
        repo = sample_comparison.head.commit.repository
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "text": "\n".join(
                    [
                        f"## [Codecov](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1) Report",
                        "Attention: Patch coverage is `66.66667%` with `1 line` in your changes missing coverage. Please review.",
                        f"> Project coverage is 60.00%. Comparing base [(`{base_commit.commitid[:7]}`)](test.example.br/gh/{test_name}/{repo.name}/commit/{base_commit.commitid}?dropdown=coverage&el=desc) to head [(`{head_commit.commitid[:7]}`)](test.example.br/gh/{test_name}/{repo.name}/commit/{head_commit.commitid}?dropdown=coverage&el=desc).",
                        "",
                        f"| [Files with missing lines](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=tree) | Patch % | Lines |",
                        "|---|---|---|",
                        f"| [file\\_1.go](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go#diff-ZmlsZV8xLmdv) | 66.67% | [1 Missing :warning: ](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree) |",
                        "",
                        f"| [Files with missing lines](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
                        "|---|---|---|---|",
                        f"| [file\\_1.go](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree&filepath=file_1.go#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
                        "",
                        f"... and [1 file with indirect coverage changes](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}/indirect-changes?src=pr&el=tree-more)",
                        "",
                        "------",
                        "",
                        f"[Continue to review full report in Codecov by Sentry](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=continue).",
                        "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)",
                        "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
                        f"> Powered by [Codecov](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=footer). Last update [{base_commit.commitid[:7]}...{head_commit.commitid[:7]}](test.example.br/gh/{test_name}/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=lastupdated). Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
                        "",
                    ],
                ),
            },
        }
        assert expected_result["output"]["text"].split("\n") == result["output"][
            "text"
        ].split("\n")
        assert expected_result == result

    def test_build_default_payload_comment_off(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"comment": False},
            repository_service=mock_repo_provider,
        )
        result = notifier.build_payload(sample_comparison)
        repo = sample_comparison.head.commit.repository
        base_commit = sample_comparison.project_coverage_base.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload_comment_off/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            },
        }
        assert expected_result == result

    def test_build_default_payload_negative_change_comment_off(
        self, sample_comparison_negative_change, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_negative_change.head.commit.repository,
            title="default",
            notifier_yaml_settings={"removed_code_behavior": "removals_only"},
            notifier_site_settings=True,
            current_yaml={"comment": False},
            repository_service=mock_repo_provider,
        )
        result = notifier.build_payload(sample_comparison_negative_change)
        repo = sample_comparison_negative_change.head.commit.repository
        base_commit = sample_comparison_negative_change.project_coverage_base.commit
        expected_result = {
            "state": "failure",
            "output": {
                "title": f"50.00% (-10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload_negative_change_comment_off/{repo.name}/pull/{sample_comparison_negative_change.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n50.00% (-10.00%) compared to {base_commit.commitid[:7]}",
            },
        }
        assert expected_result == result

    def test_build_payload_not_auto(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": "57%", "flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        repo = sample_comparison.head.commit.repository
        expected_result = {
            "state": "success",
            "output": {
                "title": "60.00% (target 57.00%)",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_not_auto/{repo.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (target 57.00%)",
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_no_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = ProjectChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        repo = sample_comparison_without_base_report.head.commit.repository
        expected_result = {
            "state": "success",
            "output": {
                "title": "No report found to compare against",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_no_base_report/{repo.name}/pull/{sample_comparison_without_base_report.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nNo report found to compare against",
            },
        }
        result = notifier.build_payload(comparison)
        assert expected_result == result

    def test_check_notify_no_path_match(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"

        notifier = ProjectChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["pathone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {
                "title": "No coverage information found on head",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_check_notify_no_path_match/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nNo coverage information found on head",
            },
            "url": f"test.example.br/gh/test_check_notify_no_path_match/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}",
        }

    def test_check_notify_single_path_match(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"

        notifier = ProjectChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["file_1.go"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )

        base_commit = sample_comparison.project_coverage_base.commit
        result = notifier.notify(sample_comparison)
        assert result.notification_successful is True
        assert result.explanation is None
        expected_result = {
            "state": "success",
            "output": {
                "title": f"62.50% (+12.50%) compared to {base_commit.commitid[0:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_check_notify_single_path_match/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n62.50% (+12.50%) compared to {base_commit.commitid[0:7]}",
            },
            "url": f"test.example.br/gh/test_check_notify_single_path_match/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}",
        }
        assert result.data_sent["state"] == expected_result["state"]
        assert (
            result.data_sent["output"]["summary"]
            == expected_result["output"]["summary"]
        )
        assert result.data_sent["output"] == expected_result["output"]

    def test_check_notify_multiple_path_match(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"

        notifier = ProjectChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["file_2.py", "file_1.go"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )

        base_commit = sample_comparison.project_coverage_base.commit
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[0:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_check_notify_multiple_path_match/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[0:7]}",
            },
            "url": f"test.example.br/gh/test_check_notify_multiple_path_match/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}",
        }

    def test_check_notify_with_paths(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        payload = {
            "state": "success",
            "output": {"title": "Codecov Report", "summary": "Summary"},
        }
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"

        notifier = ProjectChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = sample_comparison.project_coverage_base.commit
        result = notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[0:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_check_notify_with_paths/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[0:7]}",
            },
            "url": f"test.example.br/gh/test_check_notify_with_paths/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}",
        }

    def test_notify_pass_behavior_when_coverage_not_uploaded(
        self,
        sample_comparison_coverage_carriedforward,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "pass",
                "flags": ["integration", "missing"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
        head_commit = sample_comparison_coverage_carriedforward.head.commit

        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "state": "success",
                "output": {
                    "title": f"25.00% (+0.00%) compared to {base_commit.commitid[:7]}",
                    "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n25.00% (+0.00%) compared to {base_commit.commitid[:7]} [Auto passed due to carriedforward or missing coverage]",
                },
                "url": f"test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}",
            },
        )
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert (
            expected_result.data_sent["output"]["summary"]
            == result.data_sent["output"]["summary"]
        )
        assert expected_result.data_sent["output"] == result.data_sent["output"]
        assert expected_result == result

    def test_notify_pass_behavior_when_coverage_uploaded(
        self,
        sample_comparison_coverage_carriedforward,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "pass",
                "flags": ["unit"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
        head_commit = sample_comparison_coverage_carriedforward.head.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "state": "success",
                "output": {
                    "title": f"25.00% (+0.00%) compared to {base_commit.commitid[:7]}",
                    "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n25.00% (+0.00%) compared to {base_commit.commitid[:7]}",
                },
                "url": f"test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}",
            },
        )
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_include_behavior_when_coverage_not_uploaded(
        self,
        sample_comparison_coverage_carriedforward,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "include",
                "flags": ["integration", "enterprise"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
        head_commit = sample_comparison_coverage_carriedforward.head.commit

        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "state": "success",
                "output": {
                    "title": f"36.17% (+0.00%) compared to {base_commit.commitid[:7]}",
                    "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n36.17% (+0.00%) compared to {base_commit.commitid[:7]}",
                },
                "url": f"test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}",
            },
        )
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_exclude_behavior_when_coverage_not_uploaded(
        self,
        sample_comparison_coverage_carriedforward,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "exclude",
                "flags": ["missing"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = NotificationResult(
            notification_attempted=False,
            notification_successful=None,
            explanation="exclude_flag_coverage_not_uploaded_checks",
            data_sent=None,
            data_received=None,
        )
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_exclude_behavior_when_coverage_uploaded(
        self,
        sample_comparison_coverage_carriedforward,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "exclude",
                "flags": ["unit"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
        head_commit = sample_comparison_coverage_carriedforward.head.commit

        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "state": "success",
                "output": {
                    "title": f"25.00% (+0.00%) compared to {base_commit.commitid[:7]}",
                    "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n25.00% (+0.00%) compared to {base_commit.commitid[:7]}",
                },
                "url": f"test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}",
            },
        )
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_exclude_behavior_when_some_coverage_uploaded(
        self,
        sample_comparison_coverage_carriedforward,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "exclude",
                "flags": [
                    "unit",
                    "missing",
                    "integration",
                ],  # only "unit" was uploaded, but this should still notify
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
        head_commit = sample_comparison_coverage_carriedforward.head.commit

        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "state": "success",
                "output": {
                    "title": f"36.17% (+0.00%) compared to {base_commit.commitid[:7]}",
                    "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n36.17% (+0.00%) compared to {base_commit.commitid[:7]}",
                },
                "url": f"test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}",
            },
        )
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_exclude_behavior_no_flags(
        self,
        sample_comparison_coverage_carriedforward,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "exclude",
                "flags": None,
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
        head_commit = sample_comparison_coverage_carriedforward.head.commit

        # should send the check as normal if there are no flags
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "state": "success",
                "output": {
                    "title": f"65.38% (+0.00%) compared to {base_commit.commitid[:7]}",
                    "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n65.38% (+0.00%) compared to {base_commit.commitid[:7]}",
                },
                "url": f"test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison_coverage_carriedforward.pull.pullid}",
            },
        )
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert (
            expected_result.data_sent["output"]["summary"]
            == result.data_sent["output"]["summary"]
        )
        assert expected_result.data_sent["output"] == result.data_sent["output"]
        assert expected_result.data_sent == result.data_sent
        assert expected_result == result

    def test_build_payload_comments_true(self, sample_comparison, mock_configuration):
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings={},
            current_yaml={"comment": True},
            repository_service=None,
        )
        res = notifier.build_payload(sample_comparison)
        assert res == {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            },
        }

    def test_build_payload_comments_false(self, sample_comparison, mock_configuration):
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings={},
            current_yaml={"comment": False},
            repository_service=None,
        )
        res = notifier.build_payload(sample_comparison)
        assert res == {
            "state": "success",
            "output": {
                "title": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/{head_commit.repository.owner.username}/{head_commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            },
        }
