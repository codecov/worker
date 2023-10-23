import pytest
from mock import patch
from shared.reports.readonly import ReadOnlyReport
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitRepoNotFoundError,
    TorngitServerUnreachableError,
)
from shared.torngit.status import Status
from shared.yaml.user_yaml import UserYaml

from database.enums import Notification
from services.comparison import ComparisonProxy
from services.decoration import Decoration
from services.notification.notifiers.base import NotificationResult
from services.notification.notifiers.status import (
    ChangesStatusNotifier,
    PatchStatusNotifier,
    ProjectStatusNotifier,
)
from services.notification.notifiers.status.base import StatusNotifier
from services.urls import get_pull_url


def test_notification_type(mocker):
    assert (
        ProjectStatusNotifier(
            mocker.MagicMock(),
            mocker.MagicMock(),
            mocker.MagicMock(),
            mocker.MagicMock(),
            mocker.MagicMock(),
        ).notification_type
        == Notification.status_project
    )
    assert (
        ChangesStatusNotifier(
            mocker.MagicMock(),
            mocker.MagicMock(),
            mocker.MagicMock(),
            mocker.MagicMock(),
            mocker.MagicMock(),
        ).notification_type
        == Notification.status_changes
    )


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


@pytest.fixture
def comparison_100_percent_patch(sample_comparison):
    first_report = Report()
    second_report = Report()
    # MODIFIED FILE
    first_modified_file = ReportFile("modified.py")
    first_modified_file.append(17, ReportLine.create(coverage=0))
    first_modified_file.append(18, ReportLine.create(coverage=0))
    first_modified_file.append(19, ReportLine.create(coverage=1))
    first_modified_file.append(20, ReportLine.create(coverage=0))
    first_modified_file.append(21, ReportLine.create(coverage=1))
    first_modified_file.append(22, ReportLine.create(coverage=1))
    first_modified_file.append(23, ReportLine.create(coverage=0))
    first_modified_file.append(24, ReportLine.create(coverage=0))
    first_report.append(first_modified_file)
    second_modified_file = ReportFile("modified.py")
    second_modified_file.append(18, ReportLine.create(coverage=0))
    second_modified_file.append(19, ReportLine.create(coverage=0))
    second_modified_file.append(20, ReportLine.create(coverage=0))
    second_modified_file.append(21, ReportLine.create(coverage=0))
    second_modified_file.append(22, ReportLine.create(coverage=0))
    second_modified_file.append(23, ReportLine.create(coverage=1))
    second_modified_file.append(24, ReportLine.create(coverage=1))
    second_report.append(second_modified_file)
    sample_comparison.base.report = ReadOnlyReport.create_from_report(first_report)
    sample_comparison.head.report = ReadOnlyReport.create_from_report(second_report)
    return sample_comparison


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
    sample_comparison.base.report = ReadOnlyReport.create_from_report(first_report)
    sample_comparison.head.report = ReadOnlyReport.create_from_report(second_report)
    return sample_comparison


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


class TestBaseStatusNotifier(object):
    def test_can_we_set_this_status_no_pull(self, sample_comparison_without_pull):
        comparison = sample_comparison_without_pull
        only_pulls_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"only_pulls": True},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        assert not only_pulls_notifier.can_we_set_this_status(comparison)
        wrong_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"only_pulls": False, "branches": ["old.*"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        assert not wrong_branch_notifier.can_we_set_this_status(comparison)
        right_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"only_pulls": False, "branches": ["new.*"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        assert right_branch_notifier.can_we_set_this_status(comparison)
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        assert no_settings_notifier.can_we_set_this_status(comparison)
        exclude_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"only_pulls": False, "branches": ["!new_branch"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        assert not exclude_branch_notifier.can_we_set_this_status(comparison)

    @pytest.mark.asyncio
    async def test_notify_after_n_builds_flags(self, sample_comparison, mocker):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
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
        )
        mocker.patch.object(StatusNotifier, "can_we_set_this_status", return_value=True)
        result = await no_settings_notifier.notify(comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "need_more_builds"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_after_n_builds_flags2(self, sample_comparison, mocker):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["unit"]},
            notifier_site_settings=True,
            current_yaml=UserYaml(
                {
                    "coverage": {
                        "status": {
                            "project": True,
                            "patch": {"default": False, "unit": {"flags": ["unit"]}},
                            "changes": True,
                        }
                    },
                    "flags": {
                        "unit": {
                            "after_n_builds": 3,
                        }
                    },
                }
            ),
        )
        mocker.patch.object(StatusNotifier, "can_we_set_this_status", return_value=True)
        result = await no_settings_notifier.notify(comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "need_more_builds"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_cannot_set_status(self, sample_comparison, mocker):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        mocker.patch.object(
            StatusNotifier, "can_we_set_this_status", return_value=False
        )
        result = await no_settings_notifier.notify(comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "not_fit_criteria"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_no_base(
        self, sample_comparison_without_base_with_pull, mocker, mock_repo_provider
    ):
        comparison = sample_comparison_without_base_with_pull
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        no_settings_notifier.context = "fake"
        mocker.patch.object(StatusNotifier, "can_we_set_this_status", return_value=True)
        mocked_build_payload = mocker.patch.object(
            StatusNotifier,
            "build_payload",
            return_value={"state": "success", "message": "somemessage"},
        )
        mocked_send_notification = mocker.patch.object(
            StatusNotifier, "send_notification"
        )
        mocked_send_notification.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": "somemessage",
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await no_settings_notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == {
            "message": "somemessage",
            "state": "success",
            "title": "codecov/project/title",
        }
        assert result.data_received == {"id": "some_id"}

    @pytest.mark.asyncio
    async def test_notify_uncached(
        self,
        sample_comparison,
        mocker,
    ):
        comparison = sample_comparison
        payload = {
            "message": "something to say",
            "state": "success",
            "url": get_pull_url(comparison.pull),
        }

        class TestNotifier(StatusNotifier):
            async def build_payload(self, comparison):
                return payload

        notifier = TestNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        notifier.context = "fake"

        send_notification = mocker.patch.object(TestNotifier, "send_notification")
        await notifier.notify(comparison)
        send_notification.assert_called_once

    @pytest.mark.asyncio
    async def test_notify_cached(
        self,
        sample_comparison,
        mocker,
    ):
        comparison = sample_comparison

        payload = {
            "message": "something to say",
            "state": "success",
            "url": get_pull_url(comparison.pull),
        }

        class TestNotifier(StatusNotifier):
            async def build_payload(self, comparison):
                return payload

        notifier = TestNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        notifier.context = "fake"

        mocker.patch(
            "helpers.cache.NullBackend.get",
            return_value=payload,
        )

        send_notification = mocker.patch.object(TestNotifier, "send_notification")
        result = await notifier.notify(comparison)
        assert result == NotificationResult(
            notification_attempted=False,
            notification_successful=None,
            explanation="payload_unchanged",
            data_sent=None,
        )

        # payload was cached - we do not send the notification
        assert not send_notification.called

    @pytest.mark.asyncio
    async def test_send_notification(
        self, sample_comparison, mocker, mock_repo_provider
    ):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        no_settings_notifier.context = "fake"
        mocked_status_already_exists = mocker.patch.object(
            StatusNotifier, "status_already_exists"
        )
        mocked_status_already_exists.return_value = False
        mock_repo_provider.set_commit_status.side_effect = TorngitClientError(
            403, "response", "message"
        )
        payload = {"message": "something to say", "state": "success", "url": "url"}
        result = await no_settings_notifier.send_notification(comparison, payload)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == "no_write_permission"
        expected_data_sent = {
            "message": "something to say",
            "state": "success",
            "title": "codecov/fake/title",
        }
        assert result.data_sent == expected_data_sent
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_analytics(
        self, sample_comparison, mocker, mock_repo_provider
    ):

        mocker.patch("helpers.environment.is_enterprise", return_value=False)
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        no_settings_notifier.context = "fake"
        mocked_status_already_exists = mocker.patch.object(
            StatusNotifier, "status_already_exists"
        )
        mocked_status_already_exists.return_value = False
        mock_repo_provider.set_commit_status.side_effect = TorngitClientError(
            403, "response", "message"
        )
        payload = {"message": "something to say", "state": "success", "url": "url"}
        await no_settings_notifier.send_notification(comparison, payload)

    @pytest.mark.asyncio
    async def test_notify_analytics_enterprise(
        self, sample_comparison, mocker, mock_repo_provider
    ):
        mocker.patch("helpers.environment.is_enterprise", return_value=True)
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        no_settings_notifier.context = "fake"
        mocked_status_already_exists = mocker.patch.object(
            StatusNotifier, "status_already_exists"
        )
        mocked_status_already_exists.return_value = False
        mock_repo_provider.set_commit_status.side_effect = TorngitClientError(
            403, "response", "message"
        )
        payload = {"message": "something to say", "state": "success", "url": "url"}
        await no_settings_notifier.send_notification(comparison, payload)

    def test_determine_status_check_behavior_to_apply(self, sample_comparison):
        # uses component level setting if provided
        comparison = sample_comparison
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={"flag_coverage_not_uploaded_behavior": "exclude"},
            notifier_site_settings=True,
            current_yaml={
                "coverage": {
                    "status": {
                        "default_rules": {
                            "flag_coverage_not_uploaded_behavior": "pass"
                        },
                        "project": {
                            "component_check": {
                                "flag_coverage_not_uploaded_behavior": "exclude"
                            }
                        },
                    }
                }
            },
        )
        notifier.context = "fake"
        assert (
            notifier.determine_status_check_behavior_to_apply(
                comparison, "flag_coverage_not_uploaded_behavior"
            )
            == "exclude"
        )

        # uses global setting if no component setting provided
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={
                "coverage": {
                    "status": {
                        "default_rules": {
                            "flag_coverage_not_uploaded_behavior": "pass"
                        },
                        "project": {"component_check": {}},
                    }
                }
            },
        )
        notifier.context = "fake"
        assert (
            notifier.determine_status_check_behavior_to_apply(
                comparison, "flag_coverage_not_uploaded_behavior"
            )
            == "pass"
        )

        # returns None if nothing set for flag_coverage_not_uploaded_behavior behavior field
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"coverage": {"status": {"default_rules": {}, "project": {}}}},
        )
        notifier.context = "fake"
        assert (
            notifier.determine_status_check_behavior_to_apply(
                comparison, "flag_coverage_not_uploaded_behavior"
            )
            == None
        )

    def test_flag_coverage_was_uploaded_when_none_uploaded(
        self, sample_comparison_coverage_carriedforward
    ):
        comparison = sample_comparison_coverage_carriedforward
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={"flags": ["missing"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        notifier.context = "fake"
        assert notifier.flag_coverage_was_uploaded(comparison) is False

    def test_flag_coverage_was_uploaded_when_all_uploaded(
        self, sample_comparison_coverage_carriedforward
    ):
        comparison = sample_comparison_coverage_carriedforward
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={"flags": ["unit"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        notifier.context = "fake"
        assert notifier.flag_coverage_was_uploaded(comparison) is True

    def test_flag_coverage_was_uploaded_when_some_uploaded(
        self, sample_comparison_coverage_carriedforward
    ):
        comparison = sample_comparison_coverage_carriedforward
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={"flags": ["unit", "enterprise", "missing"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        notifier.context = "fake"
        assert notifier.flag_coverage_was_uploaded(comparison) is True

    def test_flag_coverage_was_uploaded_when_no_status_flags(
        self, sample_comparison_coverage_carriedforward
    ):
        comparison = sample_comparison_coverage_carriedforward
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={"flags": None},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        notifier.context = "fake"
        assert notifier.flag_coverage_was_uploaded(comparison) is True


class TestProjectStatusNotifier(object):
    @pytest.mark.asyncio
    async def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        expected_result = {
            "message": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_passing_empty_upload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            decoration_type=Decoration.passing_empty_upload,
        )
        expected_result = {
            "state": "success",
            "message": "Non-testable files changed.",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_failing_empty_upload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            decoration_type=Decoration.failing_empty_upload,
        )
        expected_result = {
            "state": "failure",
            "message": "Testable files changed",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            decoration_type=Decoration.upgrade,
        )
        base_commit = sample_comparison.base.commit
        expected_result = {
            "message": "Please activate this user to display a detailed status check",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_not_auto(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "57%",
                "removed_code_behavior": "removals_only",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {"message": "60.00% (target 57.00%)", "state": "success"}
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_not_auto_not_string(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": 57.0},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {"message": "60.00% (target 57.00%)", "state": "success"}
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_no_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = ProjectStatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = comparison.base.commit
        head_commit = comparison.head.commit
        expected_result = {
            "message": "No report found to compare against",
            "state": "success",
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_status_doesnt_exist(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.set_commit_status.return_value = {"id": "some_id"}
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await notifier.notify(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_client_side_exception(
        self, sample_comparison, mocker, mock_configuration
    ):
        mocker.patch.object(
            ProjectStatusNotifier,
            "send_notification",
            side_effect=TorngitRepoNotFoundError("response", "message"),
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        repo = sample_comparison.head.commit.repository
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation="client_side_error_provider",
            data_sent={
                "message": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "url": f"test.example.br/gh/{repo.slug}/pull/{sample_comparison.pull.pullid}",
            },
            data_received=None,
        )
        result = await notifier.notify(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_server_side_exception(
        self, sample_comparison, mocker, mock_configuration
    ):
        mocker.patch.object(
            ProjectStatusNotifier,
            "send_notification",
            side_effect=TorngitServerUnreachableError(),
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        repo = sample_comparison.head.commit.repository
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation="server_side_error_provider",
            data_sent={
                "message": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "url": f"test.example.br/gh/{repo.slug}/pull/{sample_comparison.pull.pullid}",
            },
            data_received=None,
        )
        result = await notifier.notify(sample_comparison)
        assert expected_result.data_sent == result.data_sent
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_pass_behavior_when_coverage_not_uploaded(
        self, sample_comparison_coverage_carriedforward, mock_repo_provider
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.set_commit_status.return_value = {"id": "some_id"}
        notifier = ProjectStatusNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "pass",
                "flags": ["integration", "missing"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison_coverage_carriedforward.base.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": f"25.00% (+0.00%) compared to {base_commit.commitid[:7]} [Auto passed due to carriedforward or missing coverage]",
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_pass_behavior_when_coverage_uploaded(
        self, sample_comparison_coverage_carriedforward, mock_repo_provider
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.set_commit_status.return_value = {"id": "some_id"}
        notifier = ProjectStatusNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "pass",
                "flags": ["unit"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison_coverage_carriedforward.base.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": f"25.00% (+0.00%) compared to {base_commit.commitid[:7]}",  # no message indicating auto-pass
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_include_behavior_when_coverage_not_uploaded(
        self, sample_comparison_coverage_carriedforward, mock_repo_provider
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.set_commit_status.return_value = {"id": "some_id"}
        notifier = ProjectStatusNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "include",
                "flags": ["integration", "enterprise"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison_coverage_carriedforward.base.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": f"36.17% (+0.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_exclude_behavior_when_coverage_not_uploaded(
        self, sample_comparison_coverage_carriedforward, mock_repo_provider
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        notifier = ProjectStatusNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "exclude",
                "flags": ["missing"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = NotificationResult(
            notification_attempted=False,
            notification_successful=None,
            explanation="exclude_flag_coverage_not_uploaded_checks",
            data_sent=None,
            data_received=None,
        )
        result = await notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_exclude_behavior_when_coverage_uploaded(
        self, sample_comparison_coverage_carriedforward, mock_repo_provider
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.set_commit_status.return_value = {"id": "some_id"}
        notifier = ProjectStatusNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "exclude",
                "flags": ["unit"],
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison_coverage_carriedforward.base.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": f"25.00% (+0.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_exclude_behavior_when_some_coverage_uploaded(
        self, sample_comparison_coverage_carriedforward, mock_repo_provider
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.set_commit_status.return_value = {"id": "some_id"}
        notifier = ProjectStatusNotifier(
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
        )
        base_commit = sample_comparison_coverage_carriedforward.base.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": f"36.17% (+0.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_exclude_behavior_no_flags(
        self, sample_comparison_coverage_carriedforward, mock_repo_provider
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_repo_provider.set_commit_status.return_value = {"id": "some_id"}
        notifier = ProjectStatusNotifier(
            repository=sample_comparison_coverage_carriedforward.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "flag_coverage_not_uploaded_behavior": "exclude",
                "flags": None,
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison_coverage_carriedforward.base.commit
        # should send the check as normal if there are no flags
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": f"65.38% (+0.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "title": "codecov/project/title",
            },
            data_received={"id": "some_id"},
        )
        result = await notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_path_filter(
        self, sample_comparison, mock_repo_provider, mock_configuration, mocker
    ):
        mocked_send_notification = mocker.patch.object(
            ProjectStatusNotifier, "send_notification"
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["file_1.go"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        expected_result = {
            "message": f"62.50% (+12.50%) compared to {base_commit.commitid[:7]}",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison.head.commit.repository.slug}/pull/{sample_comparison.pull.pullid}",
        }
        result = await notifier.notify(sample_comparison)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(sample_comparison, expected_result)

    @pytest.mark.asyncio
    async def test_notify_path_and_flags_filter_nothing_on_base(
        self, sample_comparison, mock_repo_provider, mock_configuration, mocker
    ):
        mocked_send_notification = mocker.patch.object(
            ProjectStatusNotifier, "send_notification"
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["file_1.go"], "flags": ["unit"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        expected_result = {
            # base report does not have unit flag, so there is no coverage there
            "message": "No coverage information found on base report",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison.head.commit.repository.slug}/pull/{sample_comparison.pull.pullid}",
        }
        result = await notifier.notify(sample_comparison)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(sample_comparison, expected_result)

    @pytest.mark.asyncio
    async def test_notify_path_and_flags_filter_something_on_base(
        self,
        sample_comparison_matching_flags,
        mock_repo_provider,
        mock_configuration,
        mocker,
    ):
        mocked_send_notification = mocker.patch.object(
            ProjectStatusNotifier, "send_notification"
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison_matching_flags.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["file_1.go"], "flags": ["unit"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison_matching_flags.base.commit
        expected_result = {
            # base report does not have unit flag, so there is no coverage there
            "message": f"100.00% (+0.00%) compared to {base_commit.commitid[:7]}",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison_matching_flags.head.commit.repository.slug}/pull/{sample_comparison_matching_flags.pull.pullid}",
        }
        result = await notifier.notify(sample_comparison_matching_flags)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(
            sample_comparison_matching_flags, expected_result
        )

    @pytest.mark.asyncio
    async def test_notify_pass_via_removals_only_behavior(
        self, mock_configuration, sample_comparison, mocker
    ):
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy,
            "get_impacted_files",
            return_value={
                "files": [
                    {
                        "base_name": "tests/file1.py",
                        "head_name": "tests/file1.py",
                        # Not complete, but we only care about these fields
                        "removed_diff_coverage": [],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                    {
                        "base_name": "tests/file2.go",
                        "head_name": "tests/file2.go",
                        "removed_diff_coverage": [[1, "h"], [3, None]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                ],
            },
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "80%",
                "removed_code_behavior": "removals_only",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "60.00% (target 80.00%), passed because this change only removed code",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    @pytest.mark.asyncio
    async def test_notify_pass_adjust_base_behavior(
        slef, mock_configuration, sample_comparison_negative_change, mocker
    ):
        sample_comparison = sample_comparison_negative_change
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy,
            "get_impacted_files",
            return_value={
                "files": [
                    {
                        "base_name": "tests/file1.py",
                        "head_name": "tests/file1.py",
                        # Not complete, but we only care about these fields
                        "removed_diff_coverage": [[1, "h"], [3, "h"], [4, "m"]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                    {
                        "base_name": "tests/file2.go",
                        "head_name": "tests/file2.go",
                        "removed_diff_coverage": [[1, "h"]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                ],
            },
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"removed_code_behavior": "adjust_base"},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": f"50.00% (-10.00%) compared to {sample_comparison.base.commit.commitid[:7]}, passed because coverage increased by +0.00% when compared to adjusted base (50.00%)",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    @pytest.mark.asyncio
    async def test_notify_removed_code_behavior_fail(
        self, mock_configuration, sample_comparison, mocker
    ):
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy,
            "get_impacted_files",
            return_value={
                "files": [
                    {
                        "base_name": "tests/file1.py",
                        "head_name": "tests/file1.py",
                        # Not complete, but we only care about these fields
                        "removed_diff_coverage": [[1, "h"]],
                        "added_diff_coverage": [[2, "h"], [3, "h"]],
                        "unexpected_line_changes": [],
                    },
                    {
                        "base_name": "tests/file2.go",
                        "head_name": "tests/file2.go",
                        "removed_diff_coverage": [[1, "h"], [3, None]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                ],
            },
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "80%",
                "removed_code_behavior": "removals_only",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "60.00% (target 80.00%)",
            "state": "failure",
        }
        result = await notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    @pytest.mark.asyncio
    async def test_notify_adjust_base_behavior_fail(
        slef, mock_configuration, sample_comparison_negative_change, mocker
    ):
        sample_comparison = sample_comparison_negative_change
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy,
            "get_impacted_files",
            return_value={
                "files": [
                    {
                        "base_name": "tests/file1.py",
                        "head_name": "tests/file1.py",
                        # Not complete, but we only care about these fields
                        "removed_diff_coverage": [[1, "h"], [3, "m"], [4, "m"]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                    {
                        "base_name": "tests/file2.go",
                        "head_name": "tests/file2.go",
                        "removed_diff_coverage": [],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                ],
            },
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"removed_code_behavior": "adjust_base"},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": f"50.00% (-10.00%) compared to {sample_comparison.base.commit.commitid[:7]}",
            "state": "failure",
        }
        result = await notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    @pytest.mark.asyncio
    async def test_notify_adjust_base_behavior_skips_if_target_coverage_defined(
        slef, mock_configuration, sample_comparison_negative_change, mocker
    ):
        sample_comparison = sample_comparison_negative_change
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy, "get_impacted_files"
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "removed_code_behavior": "adjust_base",
                "target": "80%",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": f"50.00% (target 80.00%)",
            "state": "failure",
        }
        result = await notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_removed_code_behavior_unknown(
        self, mock_configuration, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "80%",
                "removed_code_behavior": "not_valid",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "60.00% (target 80.00%)",
            "state": "failure",
        }
        result = await notifier.build_payload(sample_comparison)
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_notify_fully_covered_patch_behavior_fail(
        self,
        comparison_with_multiple_changes,
        mock_repo_provider,
        mock_configuration,
        multiple_diff_changes,
        mocker,
    ):
        json_diff = multiple_diff_changes
        mock_repo_provider.get_compare.return_value = {"diff": json_diff}
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy,
            "get_impacted_files",
            return_value={
                "files": [
                    {
                        "base_name": "tests/file1.py",
                        "head_name": "tests/file1.py",
                        # Not complete, but we only care about these fields
                        "removed_diff_coverage": [[1, "h"]],
                        "added_diff_coverage": [[2, "h"], [3, "h"]],
                        "unexpected_line_changes": [],
                    },
                    {
                        "base_name": "tests/file2.go",
                        "head_name": "tests/file2.go",
                        "removed_diff_coverage": [[1, "h"], [3, None]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                ],
            },
        )
        notifier = ProjectStatusNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "70%",
                "removed_code_behavior": "fully_covered_patch",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "50.00% (target 70.00%)",
            "state": "failure",
        }
        result = await notifier.build_payload(comparison_with_multiple_changes)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    @pytest.mark.asyncio
    async def test_notify_fully_covered_patch_behavior_success(
        self,
        comparison_100_percent_patch,
        mock_repo_provider,
        mock_configuration,
        multiple_diff_changes,
        mocker,
    ):
        json_diff = multiple_diff_changes
        mock_repo_provider.get_compare.return_value = {"diff": json_diff}
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy,
            "get_impacted_files",
            return_value={
                "files": [
                    {
                        "base_name": "tests/file1.py",
                        "head_name": "tests/file1.py",
                        # Not complete, but we only care about these fields
                        "removed_diff_coverage": [[1, "h"]],
                        "added_diff_coverage": [[2, "h"], [3, "h"]],
                        "unexpected_line_changes": [],
                    },
                    {
                        "base_name": "tests/file2.go",
                        "head_name": "tests/file2.go",
                        "removed_diff_coverage": [[1, "h"], [3, None]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                ],
            },
        )
        notifier = ProjectStatusNotifier(
            repository=comparison_100_percent_patch.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "70%",
                "removed_code_behavior": "fully_covered_patch",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "28.57% (target 70.00%), passed because patch was fully covered by tests with no unexpected coverage changes",
            "state": "success",
        }
        result = await notifier.build_payload(comparison_100_percent_patch)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    @pytest.mark.asyncio
    async def test_notify_fully_covered_patch_behavior_no_coverage_change(
        self, mock_configuration, sample_comparison, mocker
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        mock_get_impacted_files = mocker.patch.object(
            ComparisonProxy,
            "get_impacted_files",
            return_value={
                "files": [
                    {
                        "base_name": "tests/file1.py",
                        "head_name": "tests/file1.py",
                        # Not complete, but we only care about these fields
                        "removed_diff_coverage": [[1, "h"]],
                        "added_diff_coverage": [[2, "h"], [3, "h"]],
                        "unexpected_line_changes": [],
                    },
                    {
                        "base_name": "tests/file2.go",
                        "head_name": "tests/file2.go",
                        "removed_diff_coverage": [[1, "h"], [3, None]],
                        "added_diff_coverage": [],
                        "unexpected_line_changes": [],
                    },
                ],
            },
        )
        mocker.patch.object(
            sample_comparison,
            "get_diff",
            return_value={
                "files": {
                    "file_1.go": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["105", "8", "105", "9"],
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
                                "header": ["1046", "12", "1047", "19"],
                                "lines": [
                                    " ",
                                    " You may need to configure a ``.coveragerc`` file. Learn more",
                                    " ",
                                    "-We highly suggest adding `source` to your ``.coveragerc``",
                                    "+We highly suggest adding ``source`` to your ``.coveragerc`",
                                    " ",
                                    " .. code-block:: ini",
                                    " ",
                                    "    [run]",
                                    "    source=your_package_name",
                                    "+   ",
                                    "+If there are multiple sources, you instead should add ``include",
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
                                "header": ["10150", "5", "10158", "4"],
                                "lines": [
                                    " * Twitter: `@codecov <https://twitter.com/codecov>`_.",
                                    " * Email: `hello@codecov.io <hello@codecov.io>`_.",
                                    " ",
                                    "-We are happy to help if you have any questions. ",
                                    "-",
                                    "+We are happy to help if you have any questions. .",
                                ],
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    },
                    "file_2.py": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["10", "8", "10", "9"],
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
                                "header": ["50", "12", "51", "19"],
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
                        ],
                        "stats": {"added": 11, "removed": 4},
                    },
                }
            },
        )
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "70%",
                "removed_code_behavior": "fully_covered_patch",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "60.00% (target 70.00%), passed because coverage was not affected by patch",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()


class TestPatchStatusNotifier(object):
    @pytest.mark.asyncio
    async def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "66.67% of diff hit (target 50.00%)",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "message": "Please activate this user to display a detailed status check",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_target_coverage_failure(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": "70%"},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "66.67% of diff hit (target 70.00%)",
            "state": "failure",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_not_auto_not_string(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": 57.0},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "66.67% of diff hit (target 57.00%)",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_target_coverage_failure_witinh_threshold(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        third_file = ReportFile("file_3.c")
        third_file.append(100, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(101, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(102, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(103, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        sample_comparison.base.report.append(third_file)
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"threshold": "5"},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "66.67% of diff hit (within 5.00% threshold of 70.00%)",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
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
                            }
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            "message": f"Coverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_no_diff_no_base_report(
        self,
        sample_comparison_without_base_with_pull,
        mock_repo_provider,
        mock_configuration,
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
        comparison = sample_comparison_without_base_with_pull
        notifier = PatchStatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {"message": f"Coverage not affected", "state": "success"}
        result = await notifier.build_payload(comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_without_base_report(
        self,
        sample_comparison_without_base_report,
        mock_repo_provider,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = PatchStatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": f"No report found to compare against",
            "state": "success",
        }
        result = await notifier.build_payload(comparison)
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

        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "50.00% of diff hit (target 76.92%)",
            "state": "failure",
        }
        result = await notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result == result


class TestChangesStatusNotifier(object):
    @pytest.mark.asyncio
    async def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "No unexpected coverage changes found",
            "state": "success",
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "message": "Please activate this user to display a detailed status check",
            "state": "success",
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

        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "3 files have unexpected coverage changes not visible in diff",
            "state": "failure",
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
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        notifier = ChangesStatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        expected_result = {
            "message": "Unable to determine changes, no report found at pull request base",
            "state": "success",
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_path_filter(
        self, sample_comparison, mock_repo_provider, mock_configuration, mocker
    ):
        mocked_send_notification = mocker.patch.object(
            ChangesStatusNotifier, "send_notification"
        )
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"paths": ["file_1.go"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
        )
        base_commit = sample_comparison.base.commit
        expected_result = {
            "message": "No unexpected coverage changes found",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison.head.commit.repository.slug}/pull/{sample_comparison.pull.pullid}",
        }
        result = await notifier.notify(sample_comparison)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(sample_comparison, expected_result)

    @pytest.mark.asyncio
    async def test_build_passing_empty_upload_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            decoration_type=Decoration.passing_empty_upload,
        )
        expected_result = {"state": "success", "message": "Non-testable files changed."}
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result
