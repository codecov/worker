from unittest.mock import MagicMock

import pytest
from mock import AsyncMock
from shared.reports.readonly import ReadOnlyReport
from shared.reports.reportfile import ReportFile
from shared.reports.resources import Report
from shared.reports.types import ReportLine, ReportTotals
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitRepoNotFoundError,
    TorngitServerUnreachableError,
)
from shared.torngit.status import Status
from shared.typings.torngit import GithubInstallationInfo, TorngitInstanceData
from shared.yaml.user_yaml import UserYaml

from database.enums import Notification
from database.tests.factories.core import CommitFactory
from services.comparison import ComparisonProxy
from services.comparison.types import FullCommit
from services.decoration import Decoration
from services.notification.notifiers.base import NotificationResult
from services.notification.notifiers.mixins.status import (
    HELPER_TEXT_MAP,
    HelperTextKey,
    HelperTextTemplate,
)
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
    sample_comparison.project_coverage_base.report = ReadOnlyReport.create_from_report(
        first_report
    )
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
    sample_comparison.project_coverage_base.report = ReadOnlyReport.create_from_report(
        first_report
    )
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
            repository_service={},
        )
        assert not only_pulls_notifier.can_we_set_this_status(comparison)
        wrong_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"only_pulls": False, "branches": ["old.*"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        assert not wrong_branch_notifier.can_we_set_this_status(comparison)
        right_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"only_pulls": False, "branches": ["new.*"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        assert right_branch_notifier.can_we_set_this_status(comparison)
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        assert no_settings_notifier.can_we_set_this_status(comparison)
        exclude_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"only_pulls": False, "branches": ["!new_branch"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        assert not exclude_branch_notifier.can_we_set_this_status(comparison)

    def test_notify_after_n_builds_flags(self, sample_comparison, mocker):
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
            repository_service={},
        )
        mocker.patch.object(StatusNotifier, "can_we_set_this_status", return_value=True)
        result = no_settings_notifier.notify(comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "need_more_builds"
        assert result.data_sent is None
        assert result.data_received is None

    def test_notify_after_n_builds_flags2(self, sample_comparison, mocker):
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
            repository_service={},
        )
        mocker.patch.object(StatusNotifier, "can_we_set_this_status", return_value=True)
        result = no_settings_notifier.notify(comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "need_more_builds"
        assert result.data_sent is None
        assert result.data_received is None

    def test_notify_cannot_set_status(self, sample_comparison, mocker):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        mocker.patch.object(
            StatusNotifier, "can_we_set_this_status", return_value=False
        )
        result = no_settings_notifier.notify(comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "not_fit_criteria"
        assert result.data_sent is None
        assert result.data_received is None

    def test_notify_no_base(
        self, sample_comparison_without_base_with_pull, mocker, mock_repo_provider
    ):
        comparison = sample_comparison_without_base_with_pull
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
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
        result = no_settings_notifier.notify(comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == {
            "message": "somemessage",
            "state": "success",
            "title": "codecov/project/title",
        }
        assert result.data_received == {"id": "some_id"}

    def test_notify_uncached(
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
            def build_payload(self, comparison):
                return payload

        notifier = TestNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        notifier.context = "fake"

        send_notification = mocker.patch.object(TestNotifier, "send_notification")
        notifier.notify(comparison)
        send_notification.assert_called_once

    def test_notify_multiple_shas(
        self,
        sample_comparison,
        mocker,
    ):
        comparison = sample_comparison
        comparison.context.gitlab_extra_shas = set(["extra_sha"])
        payload = {
            "message": "something to say",
            "state": "success",
            "url": get_pull_url(comparison.pull),
        }

        def set_status_side_effect(commit, *args, **kwargs):
            return {"id": f"{commit}-status-set"}

        class TestNotifier(StatusNotifier):
            def build_payload(self, comparison):
                return payload

            def get_github_app_used(self) -> None:
                return None

            def status_already_exists(
                self, comparison: ComparisonProxy, title, state, description
            ) -> bool:
                return False

        fake_repo_service = MagicMock(
            name="fake_repo_provider",
            set_commit_status=AsyncMock(side_effect=set_status_side_effect),
        )
        notifier = TestNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=fake_repo_service,
        )
        notifier.context = "fake"

        result = notifier.notify(comparison)
        assert result == NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                "message": payload["message"],
                "state": payload["state"],
                "title": "codecov/fake/title",
            },
            data_received={"id": f"{comparison.head.commit.commitid}-status-set"},
            github_app_used=None,
        )
        assert fake_repo_service.set_commit_status.call_count == 2

    def test_notify_cached(
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
            def build_payload(self, comparison):
                return payload

        notifier = TestNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        notifier.context = "fake"

        mocker.patch(
            "shared.helpers.cache.NullBackend.get",
            return_value=payload,
        )

        send_notification = mocker.patch.object(TestNotifier, "send_notification")
        result = notifier.notify(comparison)
        assert result == NotificationResult(
            notification_attempted=False,
            notification_successful=None,
            explanation="payload_unchanged",
            data_sent=None,
        )

        # payload was cached - we do not send the notification
        assert not send_notification.called

    def test_send_notification(self, sample_comparison, mocker, mock_repo_provider):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        no_settings_notifier.context = "fake"
        mocked_status_already_exists = mocker.patch.object(
            StatusNotifier, "status_already_exists"
        )
        mocked_status_already_exists.return_value = False
        mock_repo_provider.set_commit_status.side_effect = TorngitClientError(
            403, "response", "message"
        )
        payload = {
            "message": "something to say",
            "state": "success",
            "url": "url",
            "included_helper_text": "yayaya",
        }
        result = no_settings_notifier.send_notification(comparison, payload)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == "no_write_permission"
        expected_data_sent = {
            "message": "something to say",
            "state": "success",
            "title": "codecov/fake/title",
            "included_helper_text": "yayaya",
        }
        assert result.data_sent == expected_data_sent
        assert result.data_received is None

    def test_notify_analytics(self, sample_comparison, mocker, mock_repo_provider):
        mocker.patch("helpers.environment.is_enterprise", return_value=False)
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
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
        no_settings_notifier.send_notification(comparison, payload)

    def test_notify_analytics_enterprise(
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
            repository_service=mock_repo_provider,
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
        no_settings_notifier.send_notification(comparison, payload)

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
            repository_service={},
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
            repository_service={},
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
            repository_service={},
        )
        notifier.context = "fake"
        assert (
            notifier.determine_status_check_behavior_to_apply(
                comparison, "flag_coverage_not_uploaded_behavior"
            )
            is None
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
            repository_service={},
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
            repository_service={},
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
            repository_service={},
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
            repository_service={},
        )
        notifier.context = "fake"
        assert notifier.flag_coverage_was_uploaded(comparison) is True

    @pytest.mark.parametrize(
        "fake_torngit_data, expected",
        [
            (TorngitInstanceData(), None),
            (TorngitInstanceData(installation=None), None),
            (
                TorngitInstanceData(
                    installation=GithubInstallationInfo(
                        installation_id="owner.integration_id"
                    )
                ),
                None,
            ),
            (TorngitInstanceData(installation=GithubInstallationInfo(id=12)), 12),
        ],
    )
    def test_get_github_app_used(
        self, fake_torngit_data, expected, sample_comparison_coverage_carriedforward
    ):
        fake_torngit = MagicMock(data=fake_torngit_data, name="fake_torngit")
        comparison = sample_comparison_coverage_carriedforward
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={"flags": None},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=fake_torngit,
        )
        notifier.context = "fake"
        assert notifier.get_github_app_used() == expected

    def test_get_github_app_used_no_repository_service(
        self, sample_comparison_coverage_carriedforward
    ):
        comparison = sample_comparison_coverage_carriedforward
        notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title="component_check",
            notifier_yaml_settings={"flags": None},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=None,
        )
        notifier.context = "fake"
        assert notifier.get_github_app_used() is None


class TestProjectStatusNotifier(object):
    def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = sample_comparison.project_coverage_base.commit
        expected_result = {
            "message": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_passing_empty_upload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
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
            "message": "Non-testable files changed.",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_failing_empty_upload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
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
            "message": "Testable files changed",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.upgrade,
        )
        base_commit = sample_comparison.project_coverage_base.commit
        expected_result = {
            "message": "Please activate this user to display a detailed status check",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_not_auto(
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "60.00% (target 57.00%)",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_not_auto_not_string(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": 57.0},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "60.00% (target 57.00%)",
            "state": "success",
            "included_helper_text": {},
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
        notifier = ProjectStatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "No report found to compare against",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(comparison)
        assert expected_result == result

    def test_notify_status_doesnt_exist(
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
            repository_service=mock_repo_provider,
        )
        base_commit = sample_comparison.project_coverage_base.commit
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
        result = notifier.notify(sample_comparison)
        assert expected_result == result

    def test_notify_client_side_exception(
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
            repository_service={},
        )
        base_commit = sample_comparison.project_coverage_base.commit
        repo = sample_comparison.head.commit.repository
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation="client_side_error_provider",
            data_sent={
                "message": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "url": f"test.example.br/gh/{repo.slug}/pull/{sample_comparison.pull.pullid}",
                "included_helper_text": {},
            },
            data_received=None,
        )
        result = notifier.notify(sample_comparison)
        assert expected_result == result

    def test_notify_server_side_exception(
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
            repository_service={},
        )
        base_commit = sample_comparison.project_coverage_base.commit
        repo = sample_comparison.head.commit.repository
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation="server_side_error_provider",
            data_sent={
                "message": f"60.00% (+10.00%) compared to {base_commit.commitid[:7]}",
                "state": "success",
                "url": f"test.example.br/gh/{repo.slug}/pull/{sample_comparison.pull.pullid}",
                "included_helper_text": {},
            },
            data_received=None,
        )
        result = notifier.notify(sample_comparison)
        assert expected_result.data_sent == result.data_sent
        assert expected_result == result

    def test_notify_pass_behavior_when_coverage_not_uploaded(
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
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
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
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_pass_behavior_when_coverage_uploaded(
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
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
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
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_include_behavior_when_coverage_not_uploaded(
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
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
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
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_exclude_behavior_when_coverage_not_uploaded(
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
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
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
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_exclude_behavior_when_some_coverage_uploaded(
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
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
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
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_exclude_behavior_no_flags(
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
            repository_service=mock_repo_provider,
        )
        base_commit = (
            sample_comparison_coverage_carriedforward.project_coverage_base.commit
        )
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
        result = notifier.notify(sample_comparison_coverage_carriedforward)
        assert expected_result == result

    def test_notify_path_filter(
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
            repository_service=mock_repo_provider,
        )
        base_commit = sample_comparison.project_coverage_base.commit
        expected_result = {
            "message": f"62.50% (+12.50%) compared to {base_commit.commitid[:7]}",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison.head.commit.repository.slug}/pull/{sample_comparison.pull.pullid}",
            "included_helper_text": {},
        }
        result = notifier.notify(sample_comparison)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(sample_comparison, expected_result)

    def test_notify_path_and_flags_filter_nothing_on_base(
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            # base report does not have unit flag, so there is no coverage there
            "message": "No coverage information found on base report",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison.head.commit.repository.slug}/pull/{sample_comparison.pull.pullid}",
            "included_helper_text": {},
        }
        result = notifier.notify(sample_comparison)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(sample_comparison, expected_result)

    def test_notify_path_and_flags_filter_something_on_base(
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
            repository_service=mock_repo_provider,
        )
        base_commit = sample_comparison_matching_flags.project_coverage_base.commit
        expected_result = {
            # base report does not have unit flag, so there is no coverage there
            "message": f"100.00% (+0.00%) compared to {base_commit.commitid[:7]}",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison_matching_flags.head.commit.repository.slug}/pull/{sample_comparison_matching_flags.pull.pullid}",
            "included_helper_text": {},
        }
        result = notifier.notify(sample_comparison_matching_flags)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(
            sample_comparison_matching_flags, expected_result
        )

    def test_notify_pass_via_removals_only_behavior(
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
            repository_service={},
        )
        expected_result = {
            "message": "60.00% (target 80.00%), passed because this change only removed code",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    @pytest.mark.parametrize(
        "base_totals, head_totals, impacted_files, expected",
        [
            pytest.param(
                ReportTotals(hits=1980, misses=120, partials=0),
                ReportTotals(
                    hits=1974,
                    misses=120,
                    partials=0,
                    coverage=round((1974 / (1974 + 120)) * 100, 5),
                ),
                [
                    {
                        "removed_diff_coverage": [
                            (1, "h"),
                            (2, "h"),
                            (3, "h"),
                            (4, "h"),
                            (5, "h"),
                            (6, "h"),
                            (7, "h"),
                            (8, "h"),
                            (9, "h"),
                            (10, "h"),
                            (11, "h"),
                            (12, "h"),
                            (13, "h"),
                            (14, "h"),
                            (15, "h"),
                        ]
                    }
                ],
                (
                    (
                        "success",
                        ", passed because coverage increased by 0.02% when compared to adjusted base (94.24%)",
                    ),
                    {},
                ),
                id="many_removed_hits_makes_head_more_covered_than_base",
            ),
            pytest.param(
                ReportTotals(hits=1980, misses=120, partials=0),
                ReportTotals(
                    hits=1974,
                    misses=120,
                    partials=0,
                    coverage=round((1974 / (1974 + 120)) * 100, 5),
                ),
                [
                    {
                        "removed_diff_coverage": [
                            (1, "h"),
                            (2, "h"),
                            (3, "h"),
                            (4, "h"),
                            (5, "h"),
                            (6, "h"),
                        ]
                    }
                ],
                (
                    (
                        "success",
                        ", passed because coverage increased by 0% when compared to adjusted base (94.27%)",
                    ),
                    {},
                ),
                id="many_removed_hits_makes_head_same_as_base",
            ),
            pytest.param(
                ReportTotals(hits=1980, misses=120, partials=0),
                ReportTotals(
                    hits=1974,
                    misses=120,
                    partials=0,
                    coverage=round((1974 / (1974 + 120)) * 100, 5),
                ),
                [
                    {
                        "removed_diff_coverage": [
                            (1, "h"),
                            (2, "h"),
                            (3, "h"),
                        ]
                    }
                ],
                (
                    None,
                    {
                        HelperTextKey.RCB_ADJUST_BASE.value: HELPER_TEXT_MAP[
                            HelperTextKey.RCB_ADJUST_BASE
                        ].value.format(
                            notification_type="status",
                            coverage=94.27,
                            adjusted_base_cov=94.28,
                        ),
                    },
                ),
                id="not_enough_hits_removed_for_status_to_pass",
            ),
            pytest.param(
                ReportTotals(hits=0, misses=0, partials=0),
                ReportTotals(hits=0, misses=0, partials=0, coverage="100"),
                [],
                (None, {}),
                id="zero_coverage",
            ),
        ],
    )
    def test_adjust_base_behavior(
        self, mocker, base_totals, head_totals, impacted_files, expected
    ):
        comparison = mocker.MagicMock(
            name="fake-comparison",
            get_impacted_files=MagicMock(return_value={"files": impacted_files}),
            project_coverage_base=FullCommit(
                commit=None, report=Report(totals=base_totals)
            ),
            head=FullCommit(commit=CommitFactory(), report=Report(totals=head_totals)),
        )
        settings = {"target": "auto", "threshold": "0"}
        status_mixin = ProjectStatusNotifier(
            repository="repo",
            title="fake-notifier",
            notifier_yaml_settings=settings,
            notifier_site_settings={},
            current_yaml=settings,
            repository_service={},
        )
        result = status_mixin._apply_adjust_base_behavior(
            comparison, notification_type="status"
        )
        assert result == expected

    def test_notify_pass_adjust_base_behavior(
        self, mock_configuration, sample_comparison_negative_change, mocker
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
            repository_service={},
        )
        expected_result = {
            "message": f"50.00% (-10.00%) compared to {sample_comparison.project_coverage_base.commit.commitid[:7]}, passed because coverage increased by 0% when compared to adjusted base (50.00%)",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_pass_adjust_base_behavior_with_threshold(
        self, mock_configuration, sample_comparison_negative_change, mocker
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
            notifier_yaml_settings={
                "removed_code_behavior": "adjust_base",
                "threshold": "5",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        expected_result = {
            "message": f"50.00% (-10.00%) compared to {sample_comparison.project_coverage_base.commit.commitid[:7]}, passed because coverage increased by 5.00% when compared to adjusted base (45.00%)",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_removed_code_behavior_fail(
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
            repository_service=None,
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
            repository_service=None,
        )
        expected_result = {
            "message": "60.00% (target 80.00%)",
            "state": "failure",
            "included_helper_text": {
                HelperTextKey.CUSTOM_TARGET_PROJECT: HelperTextTemplate.CUSTOM_TARGET.format(
                    context="project",
                    notification_type="status",
                    point_of_comparison="head",
                    coverage="60.00",
                    target="80.00",
                )
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_adjust_base_behavior_fail(
        self, mock_configuration, sample_comparison_negative_change, mocker
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
            repository_service={},
        )
        # included helper text for this user because they have adjust_base in their yaml
        expected_result = {
            "message": f"50.00% (-10.00%) compared to {sample_comparison.project_coverage_base.commit.commitid[:7]}",
            "state": "failure",
            "included_helper_text": {
                HelperTextKey.RCB_ADJUST_BASE.value: HELPER_TEXT_MAP[
                    HelperTextKey.RCB_ADJUST_BASE
                ].value.format(
                    notification_type="status",
                    coverage="50.00",
                    adjusted_base_cov=71.43,
                )
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_rcb_default(
        self, mock_configuration, sample_comparison_negative_change, mocker
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
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service={},
        )
        # NO helper text for this user because they have NOT specified adjust_base in their yaml
        expected_result = {
            "message": f"50.00% (-10.00%) compared to {sample_comparison.project_coverage_base.commit.commitid[:7]}",
            "state": "failure",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_adjust_base_behavior_skips_if_target_coverage_defined(
        self, mock_configuration, sample_comparison_negative_change, mocker
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
            repository_service={},
        )
        expected_result = {
            "message": "50.00% (target 80.00%)",
            "state": "failure",
            "included_helper_text": {
                HelperTextKey.CUSTOM_TARGET_PROJECT: HelperTextTemplate.CUSTOM_TARGET.format(
                    context="project",
                    notification_type="status",
                    point_of_comparison="head",
                    coverage="50.00",
                    target="80.00",
                )
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_not_called()

    def test_notify_removed_code_behavior_unknown(
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
            repository_service={},
        )
        expected_result = {
            "message": "60.00% (target 80.00%)",
            "state": "failure",
            "included_helper_text": {
                HelperTextKey.CUSTOM_TARGET_PROJECT: HelperTextTemplate.CUSTOM_TARGET.format(
                    context="project",
                    notification_type="status",
                    point_of_comparison="head",
                    coverage="60.00",
                    target="80.00",
                )
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result

    def test_notify_fully_covered_patch_behavior_fail(
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "50.00% (target 70.00%)",
            "state": "failure",
            "included_helper_text": {
                HelperTextKey.CUSTOM_TARGET_PROJECT: HelperTextTemplate.CUSTOM_TARGET.format(
                    context="project",
                    notification_type="status",
                    point_of_comparison="head",
                    coverage="50.00",
                    target="70.00",
                )
            },
        }
        result = notifier.build_payload(comparison_with_multiple_changes)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_fully_covered_patch_behavior_fail_indirect_changes(
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
                        "unexpected_line_changes": "any value in this field",
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "50.00% (target 70.00%)",
            "state": "failure",
            "included_helper_text": {
                HelperTextKey.CUSTOM_TARGET_PROJECT.value: HelperTextTemplate.CUSTOM_TARGET.value.format(
                    context="project",
                    notification_type="status",
                    point_of_comparison="head",
                    coverage="50.00",
                    target="70.00",
                ),
                HelperTextKey.RCB_INDIRECT_CHANGES.value: HELPER_TEXT_MAP[
                    HelperTextKey.RCB_INDIRECT_CHANGES
                ].value.format(
                    context="project",
                    notification_type="status",
                ),
            },
        }
        result = notifier.build_payload(comparison_with_multiple_changes)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_fully_covered_patch_behavior_success(
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "28.57% (target 70.00%), passed because patch was fully covered by tests, and no indirect coverage changes",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(comparison_100_percent_patch)
        assert result == expected_result
        mock_get_impacted_files.assert_called()

    def test_notify_fully_covered_patch_behavior_no_coverage_change(
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
            repository_service={},
        )
        expected_result = {
            "message": "60.00% (target 70.00%), passed because coverage was not affected by patch",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert result == expected_result
        mock_get_impacted_files.assert_called()


class TestPatchStatusNotifier(object):
    def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "66.67% of diff hit (target 50.00%)",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "message": "Please activate this user to display a detailed status check",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_target_coverage_failure(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": "70%"},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "66.67% of diff hit (target 70.00%)",
            "state": "failure",
            "included_helper_text": {
                HelperTextKey.CUSTOM_TARGET_PATCH: HelperTextTemplate.CUSTOM_TARGET.format(
                    context="patch",
                    notification_type="status",
                    point_of_comparison="patch",
                    coverage=66.67,
                    target="70.00",
                )
            },
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_not_auto_not_string(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"target": 57.0},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "66.67% of diff hit (target 57.00%)",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_target_coverage_failure_within_threshold(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        third_file = ReportFile("file_3.c")
        third_file.append(100, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(101, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(102, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(103, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        report = sample_comparison.project_coverage_base.report.inner_report
        report.append(third_file)
        sample_comparison.project_coverage_base.report = (
            ReadOnlyReport.create_from_report(report)
        )
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"threshold": "5"},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "66.67% of diff hit (within 5.00% threshold of 70.00%)",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_get_patch_status_bad_threshold(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        third_file = ReportFile("file_3.c")
        third_file.append(100, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(101, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(102, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(103, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        report = sample_comparison.project_coverage_base.report.inner_report
        report.append(third_file)
        sample_comparison.project_coverage_base.report = (
            ReadOnlyReport.create_from_report(report)
        )
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"threshold": None},  # invalid value for threshold
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "66.67% of diff hit (target 70.00%)",
            "state": "failure",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_get_patch_status_bad_threshold_fixed(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        third_file = ReportFile("file_3.c")
        third_file.append(100, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(101, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(102, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        third_file.append(103, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        report = sample_comparison.project_coverage_base.report.inner_report
        report.append(third_file)
        sample_comparison.project_coverage_base.report = (
            ReadOnlyReport.create_from_report(report)
        )
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "threshold": "5%"
            },  # invalid value for threshold, caught and fixed
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "66.67% of diff hit (within 5.00% threshold of 70.00%)",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

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
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            "message": f"Coverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_payload_no_diff_no_base_report(
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "Coverage not affected",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(comparison)
        assert expected_result == result

    def test_build_payload_without_base_report(
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "No report found to compare against",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(comparison)
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
        notifier = PatchStatusNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "50.00% of diff hit (target 76.92%)",
            "state": "failure",
            "included_helper_text": {},  # not a custom target, no helper text
        }
        result = notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result == result


class TestChangesStatusNotifier(object):
    def test_build_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "No indirect coverage changes found",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result

    def test_build_upgrade_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
            decoration_type=Decoration.upgrade,
        )
        expected_result = {
            "message": "Please activate this user to display a detailed status check",
            "state": "success",
            "included_helper_text": {},
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
        notifier = ChangesStatusNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "3 files have indirect coverage changes not visible in diff",
            "state": "failure",
            "included_helper_text": {
                "indirect_changes_helper_text": (
                    "Your changes status has failed because you have indirect coverage changes. "
                    "Learn more about [Unexpected Coverage Changes](https://docs.codecov.com/docs/unexpected-coverage-changes) "
                    "and [reasons for indirect coverage changes](https://docs.codecov.com/docs/unexpected-coverage-changes#reasons-for-indirect-changes)."
                )
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
        notifier = ChangesStatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "Unable to determine changes, no report found at pull request base",
            "state": "success",
            "included_helper_text": {},
        }
        result = notifier.build_payload(comparison)
        assert expected_result == result

    def test_notify_path_filter(
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
            repository_service=mock_repo_provider,
        )
        expected_result = {
            "message": "No indirect coverage changes found",
            "state": "success",
            "url": f"test.example.br/gh/{sample_comparison.head.commit.repository.slug}/pull/{sample_comparison.pull.pullid}",
            "included_helper_text": {},
        }
        result = notifier.notify(sample_comparison)
        assert result == mocked_send_notification.return_value
        mocked_send_notification.assert_called_with(sample_comparison, expected_result)

    def test_build_passing_empty_upload_payload(
        self, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        notifier = ChangesStatusNotifier(
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
            "message": "Non-testable files changed.",
            "included_helper_text": {},
        }
        result = notifier.build_payload(sample_comparison)
        assert expected_result == result
