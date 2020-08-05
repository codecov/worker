import pytest

from services.notification.notifiers.checks import (
    ProjectChecksNotifier,
    ChangesChecksNotifier,
    PatchChecksNotifier,
)
from services.notification.notifiers.checks.base import ChecksNotifier
from shared.reports.resources import ReportLine, ReportFile, Report
from services.decoration import Decoration


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
    first_modified_file.append(23, ReportLine(coverage=1))
    first_modified_file.append(24, ReportLine(coverage=1))
    first_report.append(first_modified_file)
    second_modified_file = ReportFile("modified.py")
    second_modified_file.append(18, ReportLine(coverage=1))
    second_modified_file.append(19, ReportLine(coverage=0))
    second_modified_file.append(20, ReportLine(coverage=0))
    second_modified_file.append(21, ReportLine(coverage=1))
    second_modified_file.append(22, ReportLine(coverage=0))
    second_modified_file.append(23, ReportLine(coverage=0))
    second_modified_file.append(24, ReportLine(coverage=1))
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
    sample_comparison.base.report = first_report
    sample_comparison.head.report = second_report
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


class TestBaseChecksNotifier(object):
    @pytest.mark.asyncio
    async def test_checks_no_pull(self, sample_comparison_without_pull):
        comparison = sample_comparison_without_pull
        only_pulls_notifier = ChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await only_pulls_notifier.notify(comparison)
        assert result.notification_successful is None
        assert result.explanation == "no_pull_request"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_pull_request_not_in_provider(
        self, dbsession, sample_comparison_database_pull_without_provider
    ):
        notifier = ChecksNotifier(
            repository=sample_comparison_database_pull_without_provider.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison_database_pull_without_provider)
        assert result.notification_successful is None
        assert result.explanation == "pull_request_not_in_provider"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_closed_pull_request(self, dbsession, sample_comparison):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        sample_comparison.pull.state = "closed"
        dbsession.flush()
        dbsession.refresh(sample_comparison.pull)
        result = await notifier.notify(sample_comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "pull_request_closed"
        assert result.data_sent is None
        assert result.data_received is None

    def test_create_annotations_single_segment(self, sample_comparison):
        notifier = ChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
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
            current_yaml={},
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
            current_yaml={},
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
            current_yaml={},
        )
        report = Report()
        first_deleted_file = ReportFile("file_1.go")
        first_deleted_file.append(1, ReportLine(coverage=0))
        first_deleted_file.append(2, ReportLine(coverage=0))
        first_deleted_file.append(3, ReportLine(coverage=0))
        first_deleted_file.append(5, ReportLine(coverage=0))
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
    @pytest.mark.asyncio
    async def test_build_flag_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_flag_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n66.67% of diff hit (target 50.00%)",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_upgrade_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\nThe author of this PR, codecov-test-user, is not an activated member of this organization on Codecov.\nPlease [activate this user on Codecov](test.example.br/account/gh/test_build_upgrade_payload/users) to display a detailed status check.\nCoverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.\nPlease don't hesitate to email us at success@codecov.io with any questions.",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_default_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n66.67% of diff hit (target 50.00%)",
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
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_target_coverage_failure(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": "70%", "paths": ["pathone"]},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "failure",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_target_coverage_failure/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n66.67% of diff hit (target 70.00%)",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_without_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_without_base_report/{sample_comparison_without_base_report.head.commit.repository.name}/pull/{sample_comparison_without_base_report.pull.pullid}?src=pr&el=h1)\n\nNo report found to compare against",
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
        result = await notifier.build_payload(comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_target_coverage_failure_witinh_threshold(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        third_file = ReportFile("file_3.c")
        third_file.append(100, ReportLine(coverage=1, sessions=[[0, 1]]))
        third_file.append(101, ReportLine(coverage=1, sessions=[[0, 1]]))
        third_file.append(102, ReportLine(coverage=1, sessions=[[0, 1]]))
        third_file.append(103, ReportLine(coverage=1, sessions=[[0, 1]]))
        sample_comparison.base.report.append(third_file)
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={"threshold": "5"},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_target_coverage_failure_witinh_threshold/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n66.67% of diff hit (within 5.00% threshold of 70.00%)",
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
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_with_multiple_changes(
        self,
        comparison_with_multiple_changes,
        mock_repo_provider,
        mock_configuration,
        multiple_diff_changes,
    ):
        json_diff = multiple_diff_changes
        mock_repo_provider.get_compare.return_value = {"diff": json_diff}

        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "failure",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_with_multiple_changes/{comparison_with_multiple_changes.head.commit.repository.name}/pull/{comparison_with_multiple_changes.pull.pullid}?src=pr&el=h1)\n\n50.00% of diff hit (target 76.92%)",
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
        result = await notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_no_diff(
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
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml={},
        )
        assert notifier.is_enabled()
        notifier.name
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_no_diff/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\nCoverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert notifier.notification_type.value == "checks_patch"
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_send_notification(
        self, sample_comparison, mocker, mock_repo_provider
    ):
        comparison = sample_comparison
        payload = {
            "state": "success",
            "output": {"title": "Codecov Report", "summary": f"Summary",},
        }
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.send_notification(sample_comparison, payload)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {"title": "Codecov Report", "summary": "Summary"},
        }

    @pytest.mark.asyncio
    async def test_notify(
        self, sample_comparison, mocker, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison
        payload = {
            "state": "success",
            "output": {"title": "Codecov Report", "summary": f"Summary",},
        }
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = PatchChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["pathone"]},
            notifier_site_settings=True,
            current_yaml={},
        )
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        result = await notifier.notify(sample_comparison)
        assert result.notification_successful == True
        assert result.explanation is None
        assert result.data_sent == {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_notify/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n66.67% of diff hit (target 50.00%)",
            },
            "url": f"test.example.br/gh/test_notify/{sample_comparison.head.commit.repository.name}/compare/{base_commit.commitid}...{head_commit.commitid}",
        }


class TestChangesChecksNotifier(object):
    @pytest.mark.asyncio
    async def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ChangesChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\nNo unexpected coverage changes found",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result
        assert notifier.notification_type.value == "checks_changes"

    @pytest.mark.asyncio
    async def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ChangesChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_upgrade_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\nThe author of this PR, codecov-test-user, is not an activated member of this organization on Codecov.\nPlease [activate this user on Codecov](test.example.br/account/gh/test_build_upgrade_payload/users) to display a detailed status check.\nCoverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.\nPlease don't hesitate to email us at success@codecov.io with any questions.",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_with_multiple_changes(
        self,
        comparison_with_multiple_changes,
        mock_repo_provider,
        mock_configuration,
        multiple_diff_changes,
    ):
        json_diff = multiple_diff_changes
        mock_repo_provider.get_compare.return_value = {"diff": json_diff}

        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ChangesChecksNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "failure",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_with_multiple_changes/{comparison_with_multiple_changes.head.commit.repository.name}/pull/{comparison_with_multiple_changes.pull.pullid}?src=pr&el=h1)\n\n3 files have unexpected coverage changes not visible in diff",
            },
        }
        result = await notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_without_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = ChangesChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_without_base_report/{sample_comparison_without_base_report.head.commit.repository.name}/pull/{sample_comparison_without_base_report.pull.pullid}?src=pr&el=h1)\n\nUnable to determine changes, no report found at pull request base",
            },
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result


class TestProjectChecksNotifier(object):
    @pytest.mark.asyncio
    async def test_build_flag_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.build_payload(sample_comparison)
        base_commit = sample_comparison.base.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_flag_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            },
        }
        assert result == expected_result
        assert notifier.notification_type.value == "checks_project"

    @pytest.mark.asyncio
    async def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_upgrade_payload/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\nThe author of this PR, codecov-test-user, is not an activated member of this organization on Codecov.\nPlease [activate this user on Codecov](test.example.br/account/gh/test_build_upgrade_payload/users) to display a detailed status check.\nCoverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.\nPlease don't hesitate to email us at success@codecov.io with any questions.",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_default_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"comment": {"layout": "files"}},
        )
        result = await notifier.build_payload(sample_comparison)
        repo = sample_comparison.head.commit.repository
        base_commit = sample_comparison.base.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "text": f"# [Codecov](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1) Report\n> Merging [#{sample_comparison.pull.pullid}](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/test_build_default_payload/{repo.name}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.\n> The diff coverage is `66.67%`.\n\n| [Impacted Files](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |\n|---|---|---|---|\n| [file\\_1.go](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |\n| [file\\_2.py](test.example.br/gh/test_build_default_payload/{repo.name}/pull/{sample_comparison.pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |\n",
            },
        }
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_default_payload_comment_off(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="default",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"comment": False},
        )
        result = await notifier.build_payload(sample_comparison)
        repo = sample_comparison.head.commit.repository
        base_commit = sample_comparison.base.commit
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_default_payload_comment_off/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            },
        }
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_not_auto(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": "57%", "flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml={},
        )
        repo = sample_comparison.head.commit.repository
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_not_auto/{repo.name}/pull/{sample_comparison.pull.pullid}?src=pr&el=h1)\n\n60.00% (target 57.00%)",
            },
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_no_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = ProjectChecksNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml={},
        )
        repo = sample_comparison_without_base_report.head.commit.repository
        expected_result = {
            "state": "success",
            "output": {
                "title": "Codecov Report",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_no_base_report/{repo.name}/pull/{sample_comparison_without_base_report.pull.pullid}?src=pr&el=h1)\n\nNo report found to compare against",
            },
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result
