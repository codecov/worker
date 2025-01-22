import pytest
from celery.exceptions import SoftTimeLimitExceeded
from shared.plan.constants import PlanName
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.reports.types import Change, ReportTotals
from shared.torngit.status import Status
from shared.yaml import UserYaml

from database.enums import Decoration, Notification, NotificationState
from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, EnrichedPull, FullCommit
from services.notification import NotificationService
from services.notification.notifiers import (
    CommentNotifier,
    PatchChecksNotifier,
    StatusType,
)
from services.notification.notifiers.base import NotificationResult
from services.notification.notifiers.checks import ProjectChecksNotifier
from services.notification.notifiers.checks.checks_with_fallback import (
    ChecksWithFallback,
)
from services.notification.notifiers.mixins.status import (
    CUSTOM_TARGET_TEXT_PATCH_KEY,
    CUSTOM_TARGET_TEXT_VALUE,
)


@pytest.fixture
def sample_comparison(dbsession, request):
    repository = RepositoryFactory.create(
        owner__username=request.node.name,
        owner__service="github",
        using_integration=True,
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    pull = PullFactory.create(
        repository=repository, base=base_commit.commitid, head=head_commit.commitid
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(commit=base_commit, report=None)
    head_full_commit = FullCommit(commit=head_commit, report=None)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=base_commit.commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "head": {"commitid": head_full_commit.commit.commitid},
                    "base": {
                        "commitid": base_full_commit.commit.commitid,
                        "branch": {},
                    },
                },
            ),
        )
    )


class TestNotificationService(object):
    def test_should_use_checks_notifier_yaml_field_false(self, dbsession):
        repository = RepositoryFactory.create()
        current_yaml = {"github_checks": False}
        service = NotificationService(repository, current_yaml, None)
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PROJECT.value)
            == False
        )

    @pytest.mark.parametrize(
        "repo_data,outcome",
        [
            (
                dict(
                    using_integration=True,
                    owner__integration_id=12341234,
                    owner__service="github",
                ),
                True,
            ),
            (
                dict(
                    using_integration=True,
                    owner__integration_id=12341234,
                    owner__service="gitlab",
                ),
                False,
            ),
            (
                dict(
                    using_integration=True,
                    owner__integration_id=12341234,
                    owner__service="github_enterprise",
                ),
                True,
            ),
            (
                dict(
                    using_integration=False,
                    owner__integration_id=None,
                    owner__service="github",
                ),
                False,
            ),
        ],
    )
    def test_should_use_checks_notifier_deprecated_flow(
        self, repo_data, outcome, dbsession
    ):
        repository = RepositoryFactory.create(**repo_data)
        current_yaml = {"github_checks": True}
        assert repository.owner.github_app_installations == []
        service = NotificationService(repository, current_yaml, None)
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PROJECT.value)
            == outcome
        )

    def test_should_use_checks_notifier_ghapp_all_repos_covered(self, dbsession):
        repository = RepositoryFactory.create(owner__service="github")
        ghapp_installation = GithubAppInstallation(
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            installation_id=456789,
            owner=repository.owner,
            repository_service_ids=None,
        )
        dbsession.add(ghapp_installation)
        dbsession.flush()
        current_yaml = {"github_checks": True}
        assert repository.owner.github_app_installations == [ghapp_installation]
        service = NotificationService(repository, current_yaml, None)
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PROJECT.value)
            == True
        )

    def test_use_checks_notifier_for_team_plan(self, dbsession):
        repository = RepositoryFactory.create(
            owner__service="github", owner__plan=PlanName.TEAM_MONTHLY.value
        )
        ghapp_installation = GithubAppInstallation(
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            installation_id=456789,
            owner=repository.owner,
            repository_service_ids=None,
        )
        dbsession.add(ghapp_installation)
        dbsession.flush()
        current_yaml = {"github_checks": True}
        assert repository.owner.github_app_installations == [ghapp_installation]
        service = NotificationService(repository, current_yaml, None)
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PROJECT.value)
            == False
        )
        assert (
            service._should_use_checks_notifier(status_type=StatusType.CHANGES.value)
            == False
        )
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PATCH.value)
            == True
        )

    def test_use_status_notifier_for_team_plan(self, dbsession):
        repository = RepositoryFactory.create(
            owner__service="github", owner__plan=PlanName.TEAM_MONTHLY.value
        )
        ghapp_installation = GithubAppInstallation(
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            installation_id=456789,
            owner=repository.owner,
            repository_service_ids=None,
        )
        dbsession.add(ghapp_installation)
        dbsession.flush()
        current_yaml = {"github_checks": True}
        assert repository.owner.github_app_installations == [ghapp_installation]
        service = NotificationService(repository, current_yaml, None)
        assert (
            service._should_use_status_notifier(status_type=StatusType.PROJECT.value)
            == False
        )
        assert (
            service._should_use_checks_notifier(status_type=StatusType.CHANGES.value)
            == False
        )
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PATCH.value)
            == True
        )

    def test_use_status_notifier_for_non_team_plan(self, dbsession):
        repository = RepositoryFactory.create(
            owner__service="github", owner__plan=PlanName.CODECOV_PRO_MONTHLY.value
        )
        ghapp_installation = GithubAppInstallation(
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            installation_id=456789,
            owner=repository.owner,
            repository_service_ids=None,
        )
        dbsession.add(ghapp_installation)
        dbsession.flush()
        current_yaml = {"github_checks": True}
        assert repository.owner.github_app_installations == [ghapp_installation]
        service = NotificationService(repository, current_yaml, None)
        assert (
            service._should_use_status_notifier(status_type=StatusType.PROJECT.value)
            == True
        )
        assert (
            service._should_use_checks_notifier(status_type=StatusType.CHANGES.value)
            == True
        )
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PATCH.value)
            == True
        )

    @pytest.mark.parametrize(
        "gh_installation_name",
        [GITHUB_APP_INSTALLATION_DEFAULT_NAME, "notifications-app"],
    )
    def test_should_use_checks_notifier_ghapp_some_repos_covered(
        self, dbsession, gh_installation_name
    ):
        repository = RepositoryFactory.create(owner__service="github")
        other_repo_same_owner = RepositoryFactory.create(owner=repository.owner)
        ghapp_installation = GithubAppInstallation(
            name=gh_installation_name,
            installation_id=456789,
            owner=repository.owner,
            repository_service_ids=[repository.service_id],
            app_id=123123,
            pem_path="path_to_pem_file",
        )
        dbsession.add(ghapp_installation)
        dbsession.flush()
        current_yaml = {"github_checks": True}
        assert repository.owner.github_app_installations == [ghapp_installation]
        service = NotificationService(
            repository,
            current_yaml,
            None,
            gh_installation_name_to_use=gh_installation_name,
        )
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PROJECT.value)
            == True
        )
        service = NotificationService(other_repo_same_owner, current_yaml, None)
        assert (
            service._should_use_checks_notifier(status_type=StatusType.PROJECT.value)
            == False
        )

    def test_get_notifiers_instances_only_third_party(
        self, dbsession, mock_configuration
    ):
        mock_configuration.params["services"] = {
            "notifications": {"slack": ["slack.com"]}
        }
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            owner__username="ThiagoCodecov",
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {
            "coverage": {"notify": {"slack": {"default": {"field": "1y ago"}}}}
        }
        service = NotificationService(repository, current_yaml, None)
        instances = list(service.get_notifiers_instances())
        assert len(instances) == 2
        instance = instances[0]
        assert instance.repository == repository
        assert instance.title == "default"
        assert instance.notifier_yaml_settings == {"field": "1y ago"}
        assert instance.site_settings == ["slack.com"]
        assert instance.current_yaml == current_yaml

    def test_get_notifiers_instances_checks(
        self, dbsession, mock_configuration, mocker
    ):
        repository = RepositoryFactory.create(
            owner__integration_id=123,
            owner__service="github",
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
            using_integration=True,
        )

        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {
            "coverage": {"status": {"project": True, "patch": True, "changes": True}}
        }
        mocker.patch.dict(
            os.environ, {"CHECKS_WHITELISTED_OWNERS": f"0,{repository.owner.ownerid}"}
        )
        service = NotificationService(repository, current_yaml, None)
        instances = list(service.get_notifiers_instances())
        names = sorted([instance.name for instance in instances])
        types = sorted(instance.notification_type.value for instance in instances)
        assert names == [
            "checks-changes-with-fallback",
            "checks-patch-with-fallback",
            "checks-project-with-fallback",
            "codecov-slack-app",
        ]
        assert types == [
            "checks_changes",
            "checks_patch",
            "checks_project",
            "codecov_slack_app",
        ]

    def test_get_notifiers_instances_slack_app_false(
        self, dbsession, mock_configuration, mocker
    ):
        mocker.patch("services.notification.get_config", return_value=False)
        repository = RepositoryFactory.create(
            owner__integration_id=123,
            owner__service="github",
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
            using_integration=True,
        )

        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {
            "coverage": {"status": {"project": True, "patch": True, "changes": True}}
        }
        mocker.patch.dict(
            os.environ, {"CHECKS_WHITELISTED_OWNERS": f"0,{repository.owner.ownerid}"}
        )
        service = NotificationService(repository, current_yaml, None)
        instances = list(service.get_notifiers_instances())
        names = sorted([instance.name for instance in instances])
        assert names == [
            "checks-changes-with-fallback",
            "checks-patch-with-fallback",
            "checks-project-with-fallback",
        ]

    @pytest.mark.parametrize(
        "gh_installation_name",
        [GITHUB_APP_INSTALLATION_DEFAULT_NAME, "notifications-app"],
    )
    def test_get_notifiers_instances_checks_percentage_whitelist(
        self, dbsession, mock_configuration, mocker, gh_installation_name
    ):
        repository = RepositoryFactory.create(
            owner__integration_id=123,
            owner__service="github",
            owner__ownerid=1234,
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
            using_integration=True,
        )
        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {
            "coverage": {"status": {"project": True, "patch": True, "changes": True}}
        }
        mocker.patch.dict(
            os.environ,
            {
                "CHECKS_WHITELISTED_OWNERS": "0,1",
                "CHECKS_WHITELISTED_PERCENTAGE": "35",
            },
        )
        service = NotificationService(
            repository,
            current_yaml,
            gh_installation_name,
        )
        instances = list(service.get_notifiers_instances())
        # we don't need that for slack-app notifier
        names = [
            instance._checks_notifier.name
            for instance in instances
            if instance.name != "codecov-slack-app"
        ]
        assert names == ["checks-project", "checks-patch", "checks-changes"]
        for instance in instances:
            if isinstance(instance, ChecksWithFallback):
                assert (
                    instance._checks_notifier.repository_service == gh_installation_name
                )
                assert (
                    instance._status_notifier.repository_service == gh_installation_name
                )
            else:
                assert instance.repository_service == gh_installation_name

    @pytest.mark.parametrize(
        "gh_installation_name",
        [GITHUB_APP_INSTALLATION_DEFAULT_NAME, "notifications-app"],
    )
    def test_get_notifiers_instances_comment(
        self, dbsession, mock_configuration, mocker, gh_installation_name
    ):
        repository = RepositoryFactory.create(
            owner__integration_id=123,
            owner__service="github",
            owner__ownerid=1234,
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
            using_integration=True,
        )
        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {"comment": {"layout": "condensed_header"}, "slack_app": False}
        service = NotificationService(
            repository,
            current_yaml,
            gh_installation_name,
        )
        instances = list(service.get_notifiers_instances())
        assert len(instances) == 1
        assert instances[0].repository_service == gh_installation_name

    def test_notify_general_exception(self, mocker, dbsession, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        good_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            title="good_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
            notify=mock.Mock(),
        )
        bad_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            title="bad_notifier",
            notification_type=Notification.status_project,
            decoration_type=Decoration.standard,
        )
        disabled_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=False),
            title="disabled_notifier",
            notification_type=Notification.status_patch,
            decoration_type=Decoration.standard,
            notify=mock.Mock(),
        )
        good_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"some": "data"},
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.side_effect = Exception("This is bad")
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[bad_notifier, good_notifier, disabled_notifier],
        )
        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        expected_result = [
            {"notifier": "bad_name", "title": "bad_notifier", "result": None},
            {
                "notifier": "good_name",
                "title": "good_notifier",
                "result": NotificationResult(
                    notification_attempted=True,
                    notification_successful=True,
                    explanation="",
                    data_sent={"some": "data"},
                    data_received=None,
                ),
            },
        ]
        res = notifications_service.notify(sample_comparison)
        assert expected_result == res

    def test_notify_data_sent_None(self, mocker, dbsession, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        good_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            title="good_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
            notify=mock.Mock(),
        )
        skipped_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            title="skippy_notifier",
            notification_type=Notification.status_project,
            decoration_type=Decoration.standard,
        )
        good_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"some": "data"},
        )
        skipped_expected_return = NotificationResult(
            notification_attempted=False,
            notification_successful=None,
            explanation="exclude_flag_coverage_not_uploaded_checks",
            data_sent=None,
            data_received=None,
            github_app_used=None,
        )
        skipped_notifier.notify.return_value = skipped_expected_return
        good_notifier.name = "good_name"
        skipped_notifier.name = "skippy"

        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[skipped_notifier, good_notifier],
        )

        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        expected_result = [
            {
                "notifier": "skippy",
                "title": "skippy_notifier",
                "result": skipped_expected_return,
            },
            {
                "notifier": "good_name",
                "title": "good_notifier",
                "result": NotificationResult(
                    notification_attempted=True,
                    notification_successful=True,
                    explanation="",
                    data_sent={"some": "data"},
                    data_received=None,
                ),
            },
        ]
        res = notifications_service.notify(sample_comparison)
        assert expected_result == res

    def test_notify_individual_notifier_timeout(self, mocker, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifier = mocker.MagicMock(
            title="fake_notifier",
            notify=mock.Mock(),
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        notifier.notify.side_effect = AsyncioTimeoutError
        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        res = notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        assert res == {
            "notifier": notifier.name,
            "result": None,
            "title": "fake_notifier",
        }

    def test_notify_individual_checks_project_notifier(
        self, mocker, sample_comparison, mock_repo_provider, mock_configuration
    ):
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        mock_configuration._params["setup"] = {"codecov_dashboard_url": "test"}
        current_yaml = {}
        commit = sample_comparison.head.commit
        report = Report()
        first_deleted_file = ReportFile("file_1.go")
        first_deleted_file.append(1, ReportLine.create(coverage=0, sessions=[]))
        first_deleted_file.append(2, ReportLine.create(coverage=0, sessions=[]))
        first_deleted_file.append(3, ReportLine.create(coverage=0, sessions=[]))
        first_deleted_file.append(5, ReportLine.create(coverage=0, sessions=[]))
        report.append(first_deleted_file)
        sample_comparison.head.report = report
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        notifier = ProjectChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"flags": ["flagone"]},
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        notifications_service = NotificationService(
            commit.repository, current_yaml, mock_repo_provider
        )
        res = notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )

        assert res == {
            "notifier": "checks-project",
            "title": "title",
            "result": NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation=None,
                data_sent={
                    "state": "success",
                    "output": {
                        "title": "No coverage information found on head",
                        "summary": f"[View this Pull Request on Codecov](test/gh/test_notify_individual_checks_project_notifier/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\nNo coverage information found on head",
                    },
                    "url": f"test/gh/test_notify_individual_checks_project_notifier/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}",
                },
                data_received=None,
            ),
        }

    def test_notify_individual_checks_patch_notifier_included_helper_text(
        self,
        mocker,
        sample_comparison,
        mock_repo_provider,
        mock_configuration,
        dbsession,
    ):
        """
        A failed check/status notification with included_helper_text must pass the
        included_helper_text along to the comment notifier.
        """
        pull_with_coverage = PullFactory(
            repository=sample_comparison.enriched_pull.database_pull.repository,
            commentid="1234",
        )  # add this so we don't get is_first_coverage_pull
        dbsession.add(pull_with_coverage)
        dbsession.flush()
        mock_repo_provider.get_commit_statuses.return_value = Status([])
        # add this to satisfy create_or_update_commit_notification_from_notification_result
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_configuration._params["setup"] = {"codecov_dashboard_url": "test"}
        current_yaml = {
            "coverage": {"status": {"patch": True}},
            "comment": {"layout": "condensed_header"},
            "slack_app": False,
            "github_checks": True,
        }
        commit = sample_comparison.head.commit
        report = Report()
        first_deleted_file = ReportFile("file_1.go")
        first_deleted_file.append(1, ReportLine.create(coverage=0, sessions=[]))
        first_deleted_file.append(2, ReportLine.create(coverage=0, sessions=[]))
        first_deleted_file.append(3, ReportLine.create(coverage=0, sessions=[]))
        first_deleted_file.append(5, ReportLine.create(coverage=0, sessions=[]))
        report.append(first_deleted_file)
        sample_comparison.head.report = report
        sample_comparison.project_coverage_base.report = report
        mock_repo_provider.create_check_run.return_value = 2234563
        mock_repo_provider.update_check_run.return_value = "success"
        patch_check = PatchChecksNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "70%",
                "paths": ["pathone"],
                "layout": "reach, diff, flags, files, footer",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        comment = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "target": "70%",
                "paths": ["pathone"],
                "layout": "reach, diff, flags, files, footer",
            },
            notifier_site_settings=True,
            current_yaml=UserYaml({}),
            repository_service=mock_repo_provider,
        )
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[
                patch_check,
                comment,
            ],
        )

        service = NotificationService(
            commit.repository, current_yaml, mock_repo_provider
        )
        instances = list(service.get_notifiers_instances())
        names = sorted([instance.name for instance in instances])
        types = sorted(instance.notification_type.value for instance in instances)
        assert names == ["checks-patch", "comment"]
        assert types == ["checks_patch", "comment"]

        checks_patch_result = {
            "state": "failure",
            "output": {
                "title": "66.67% of diff hit (target 70.00%)",
                "summary": f"[View this Pull Request on Codecov](test.example.br/gh/test_build_payload_target_coverage_failure/{sample_comparison.head.commit.repository.name}/pull/{sample_comparison.pull.pullid}?dropdown=coverage&src=pr&el=h1)\n\n66.67% of diff hit (target 70.00%)",
                "annotations": [],
            },
            "included_helper_text": {
                CUSTOM_TARGET_TEXT_PATCH_KEY: CUSTOM_TARGET_TEXT_VALUE.format(
                    context="patch",
                    notification_type="check",
                    coverage=66.67,
                    target="70.00",
                )
            },
        }
        # forcing this outcome from patch check notifier to test how that affects comment notifier
        mocker.patch(
            "services.notification.notifiers.checks.patch.PatchChecksNotifier.build_payload",
            return_value=checks_patch_result,
        )
        mocker.patch(
            "services.comparison.ComparisonProxy.get_behind_by",
            return_value=None,
        )
        mock_changes = [
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
        ]
        mocker.patch(
            "services.comparison.ComparisonProxy.get_changes", return_value=mock_changes
        )

        # this gets the patched result from PatchChecksNotifier, with included_helper_text
        # CommentNotifier is called next, and should have the included_helper_text in the payload
        res = service.notify(sample_comparison)

        assert len(res) == 2
        for r in res:
            if r["notifier"] == "checks-patch":
                assert (
                    checks_patch_result["included_helper_text"][
                        CUSTOM_TARGET_TEXT_PATCH_KEY
                    ]
                    in r["result"].data_sent["included_helper_text"][
                        CUSTOM_TARGET_TEXT_PATCH_KEY
                    ]
                )
            if r["notifier"] == "comment":
                assert (
                    ":x: "
                    + checks_patch_result["included_helper_text"][
                        CUSTOM_TARGET_TEXT_PATCH_KEY
                    ]
                    in r["result"].data_sent["message"]
                )

    def test_notify_individual_notifier_timeout_notification_created(
        self, mocker, dbsession, sample_comparison
    ):
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifier = mocker.MagicMock(
            title="fake_notifier",
            notify=mock.Mock(),
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        notifier.notify.side_effect = AsyncioTimeoutError
        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        res = notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        assert res == {
            "notifier": notifier.name,
            "result": None,
            "title": "fake_notifier",
        }
        dbsession.flush()
        pull = sample_comparison.enriched_pull.database_pull
        pull_commit_notifications = pull.get_head_commit_notifications()
        assert len(pull_commit_notifications) == 1

        pull_commit_notification = pull_commit_notifications[0]
        assert pull_commit_notification is not None
        assert pull_commit_notification.notification_type == notifier.notification_type
        assert pull_commit_notification.decoration_type == notifier.decoration_type
        assert pull_commit_notification.state == NotificationState.error

    def test_notify_individual_notifier_notification_created_then_updated(
        self, mocker, dbsession, sample_comparison
    ):
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifier = mocker.MagicMock(
            title="fake_notifier",
            notify=mock.Mock(),
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        # first attempt not successful
        notifier.notify.side_effect = AsyncioTimeoutError
        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        res = notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        assert res == {
            "notifier": notifier.name,
            "result": None,
            "title": "fake_notifier",
        }
        dbsession.flush()
        pull = sample_comparison.enriched_pull.database_pull
        pull_commit_notifications = pull.get_head_commit_notifications()
        assert len(pull_commit_notifications) == 1

        pull_commit_notification = pull_commit_notifications[0]
        assert pull_commit_notification is not None
        assert pull_commit_notification.decoration_type == notifier.decoration_type
        assert pull_commit_notification.state == NotificationState.error

        # second attempt successful
        notifier.notify.side_effect = [
            NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation="",
                data_sent={"some": "data"},
            )
        ]
        res = notifications_service.notify_individual_notifier(
            notifier, sample_comparison
        )
        dbsession.commit()
        assert pull_commit_notification.state == NotificationState.success

    def test_notify_individual_notifier_cancellation(self, mocker, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifier = mocker.MagicMock(
            title="fake_notifier",
            notify=mock.Mock(),
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        notifier.notify.side_effect = CancelledError()
        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        with pytest.raises(CancelledError):
            notifications_service.notify_individual_notifier(
                notifier, sample_comparison
            )

    def test_notify_timeout_exception(self, mocker, dbsession, sample_comparison):
        current_yaml = {}
        commit = sample_comparison.head.commit
        good_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mock.Mock(),
            title="good_notifier",
            notification_type=Notification.comment,
            decoration_type=Decoration.standard,
        )
        no_attempt_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mock.Mock(),
            title="no_attempt_notifier",
            notification_type=Notification.status_project,
            decoration_type=Decoration.standard,
        )
        bad_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=True),
            notify=mock.Mock(),
            title="bad_notifier",
            notification_type=Notification.status_patch,
            decoration_type=Decoration.standard,
        )
        disabled_notifier = mocker.MagicMock(
            is_enabled=mocker.MagicMock(return_value=False),
            title="disabled_notifier",
            notification_type=Notification.status_changes,
            decoration_type=Decoration.standard,
        )
        good_notifier.notify.return_value = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation="",
            data_sent={"some": "data"},
        )
        no_attempt_notifier.notify.return_value = NotificationResult(
            notification_attempted=False,
            notification_successful=None,
            explanation="no_need_to_send",
            data_sent=None,
        )
        good_notifier.name = "good_name"
        bad_notifier.name = "bad_name"
        disabled_notifier.name = "disabled_notifier_name"
        bad_notifier.notify.side_effect = SoftTimeLimitExceeded()
        mocker.patch.object(
            NotificationService,
            "get_notifiers_instances",
            return_value=[
                bad_notifier,
                good_notifier,
                disabled_notifier,
                no_attempt_notifier,
            ],
        )
        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        with pytest.raises(SoftTimeLimitExceeded):
            notifications_service.notify(sample_comparison)

        dbsession.flush()
        pull_commit_notifications = sample_comparison.enriched_pull.database_pull.get_head_commit_notifications()
        assert len(pull_commit_notifications) == 1
        for commit_notification in pull_commit_notifications:
            assert commit_notification.state in (
                NotificationState.success,
                NotificationState.error,
            )
            assert commit_notification.decoration_type == Decoration.standard
            assert commit_notification.notification_type in (
                Notification.comment,
                Notification.status_patch,
            )

    def test_not_licensed_enterprise(self, mocker, dbsession, sample_comparison):
        mocker.patch("services.notification.is_properly_licensed", return_value=False)
        mock_notify_individual_notifier = mocker.patch.object(
            NotificationService, "notify_individual_notifier"
        )
        current_yaml = {}
        commit = sample_comparison.head.commit
        notifications_service = NotificationService(
            commit.repository, current_yaml, None
        )
        expected_result = []
        res = notifications_service.notify(sample_comparison)
        assert expected_result == res
        assert not mock_notify_individual_notifier.called

    def test_get_statuses(self, mocker, dbsession, sample_comparison):
        current_yaml = {
            "coverage": {"status": {"project": True, "patch": True, "changes": True}},
            "flags": {"banana": {"carryforward": False}},
            "flag_management": {
                "default_rules": {"carryforward": False},
                "individual_flags": [
                    {
                        "name": "strawberry",
                        "carryforward": True,
                        "statuses": [{"name_prefix": "haha", "type": "patch"}],
                    }
                ],
            },
        }
        commit = sample_comparison.head.commit
        notifications_service = NotificationService(
            commit.repository, UserYaml(current_yaml), None
        )
        expected_result = [
            ("project", "default", {}),
            ("patch", "default", {}),
            ("changes", "default", {}),
            (
                "patch",
                "hahastrawberry",
                {"flags": ["strawberry"], "name_prefix": "haha", "type": "patch"},
            ),
        ]
        res = list(notifications_service.get_statuses(["unit", "banana", "strawberry"]))
        assert expected_result == res

    def test_get_component_statuses(self, mocker, dbsession, sample_comparison):
        current_yaml = {
            "component_management": {
                "default_rules": {
                    "paths": [r"src/important/.*\.cpp"],
                    "flag_regexes": [r"critical.*"],
                    "statuses": [
                        {"name_prefix": "important/", "type": "project"},
                        {
                            "name_prefix": "legacy/",
                            "type": "project",
                            "enabled": False,
                        },  # this won't be in the results because it's not enabled
                    ],
                },
                "individual_components": [
                    {
                        "component_id": "my-special-component",
                        "flag_regexes": [r"special.*"],
                        "statuses": [
                            {"name_prefix": "special/", "type": "patch"},
                            {"name_prefix": "legacy/", "type": "project"},
                        ],
                    },
                    {
                        "component_id": "inner-app",
                        "paths": [r"src/inner_app/.*"],
                        "statuses": [{"type": "patch"}],
                    },
                    {"component_id": "from_default"},
                ],
            }
        }
        commit = sample_comparison.head.commit
        notifications_service = NotificationService(
            commit.repository, UserYaml(current_yaml), None
        )
        expected_result = [
            (
                "patch",
                "special/my-special-component",
                {
                    "flags": ["special_flag"],
                    "paths": [r"src/important/.*\.cpp"],
                    "type": "patch",
                    "name_prefix": "special/",
                },
            ),
            (
                "project",
                "legacy/my-special-component",
                {
                    "flags": ["special_flag"],
                    "paths": [r"src/important/.*\.cpp"],
                    "type": "project",
                    "name_prefix": "legacy/",
                },
            ),
            (
                "patch",
                "inner-app",
                {
                    "flags": ["critical_files"],
                    "paths": [r"src/inner_app/.*"],
                    "type": "patch",
                },
            ),
            (
                "project",
                "important/from_default",
                {
                    "flags": ["critical_files"],
                    "name_prefix": "important/",
                    "type": "project",
                    "paths": [r"src/important/.*\.cpp"],
                },
            ),
        ]
        res = list(
            notifications_service.get_statuses(
                ["special_flag", "critical_files", "banana"]
            )
        )
        assert expected_result == res
