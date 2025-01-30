from datetime import datetime, timedelta

import pytest
from shared.django_apps.codecov_auth.tests.factories import (
    OwnerFactory as DjangoOwnerFactory,
)
from shared.django_apps.core.tests.factories import CommitFactory as DjangoCommitFactory
from shared.django_apps.core.tests.factories import (
    RepositoryFactory as DjangoRepositoryFactory,
)
from shared.django_apps.reports.models import ReportSession, ReportType
from shared.django_apps.reports.tests.factories import CommitReportFactory
from shared.django_apps.reports.tests.factories import (
    UploadFactory as DjangoUploadFactory,
)
from shared.plan.constants import PlanName
from shared.plan.service import PlanService
from shared.upload.utils import UploaderType, insert_coverage_measurement
from shared.utils.test_utils import mock_config_helper

from database.enums import TrialStatus
from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    ReportFactory,
    RepositoryFactory,
    UploadFactory,
)
from services.decoration import (
    BOT_USER_EMAILS,
    Decoration,
    _is_bot_account,
    determine_decoration_details,
    determine_uploads_used,
)
from services.repository import EnrichedPull
from tests.helpers import mock_all_plans_and_tiers


@pytest.fixture
def enriched_pull(dbsession, request):
    repository = RepositoryFactory.create(
        owner__username="codecov",
        owner__service="github",
        owner__unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        owner__plan="users-pr-inappm",
        name="example-python",
        image_token="abcdefghij",
        private=True,
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository,
        author__username=f"base{request.node.name[-20:]}",
        author__service="github",
    )
    head_commit = CommitFactory.create(
        repository=repository,
        author__username=f"head{request.node.name[-20:]}",
        author__service="github",
    )
    pull = PullFactory.create(
        author__service="github",
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        state="merged",
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    provider_pull = {
        "author": {"id": "7123", "username": "tomcat"},
        "base": {
            "branch": "master",
            "commitid": "b92edba44fdd29fcc506317cc3ddeae1a723dd08",
        },
        "head": {
            "branch": "reason/some-testing",
            "commitid": "a06aef4356ca35b34c5486269585288489e578db",
        },
        "number": "1",
        "id": "1",
        "state": "open",
        "title": "Creating new code for reasons no one knows",
    }
    return EnrichedPull(database_pull=pull, provider_pull=provider_pull)


@pytest.fixture
def gitlab_root_group(dbsession):
    root_group = OwnerFactory.create(
        username="root_group",
        service="gitlab",
        unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        plan="users-pr-inappm",
        plan_activated_users=[],
        plan_auto_activate=False,
        plan_user_count=3,
    )
    dbsession.add(root_group)
    dbsession.flush()
    return root_group


@pytest.fixture
def gitlab_middle_group(dbsession, gitlab_root_group):
    mid_group = OwnerFactory.create(
        username="mid_group",
        service="gitlab",
        unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi4",
        plan="users-pr-inappy",
        plan_activated_users=[],
        parent_service_id=gitlab_root_group.service_id,
        plan_auto_activate=True,
    )
    dbsession.add(mid_group)
    dbsession.flush()
    return mid_group


@pytest.fixture
def gitlab_enriched_pull_subgroup(dbsession, gitlab_middle_group):
    subgroup = OwnerFactory.create(
        username="subgroup",
        service="gitlab",
        unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        plan=None,
        parent_service_id=gitlab_middle_group.service_id,
        plan_activated_users=[],
        plan_auto_activate=True,
    )
    dbsession.add(subgroup)
    dbsession.flush()

    repository = RepositoryFactory.create(
        owner=subgroup, name="example-python", image_token="abcdefghij", private=True
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository)
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        state="merged",
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    provider_pull = {
        "author": {"id": "7123", "username": "tomcat"},
        "base": {
            "branch": "master",
            "commitid": "b92edba44fdd29fcc506317cc3ddeae1a723dd08",
        },
        "head": {
            "branch": "reason/some-testing",
            "commitid": "a06aef4356ca35b34c5486269585288489e578db",
        },
        "number": "1",
        "id": "1",
        "state": "open",
        "title": "Creating new code for reasons no one knows",
    }
    return EnrichedPull(database_pull=pull, provider_pull=provider_pull)


@pytest.fixture
def gitlab_enriched_pull_root(dbsession, gitlab_root_group):
    repository = RepositoryFactory.create(
        owner=gitlab_root_group,
        name="example-python",
        image_token="abcdefghij",
        private=True,
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository)
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        state="merged",
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    provider_pull = {
        "author": {"id": "7123", "username": "tomcat"},
        "base": {
            "branch": "master",
            "commitid": "b92edba44fdd29fcc506317cc3ddeae1a723dd08",
        },
        "head": {
            "branch": "reason/some-testing",
            "commitid": "a06aef4356ca35b34c5486269585288489e578db",
        },
        "number": "1",
        "id": "1",
        "state": "open",
        "title": "Creating new code for reasons no one knows",
    }
    return EnrichedPull(database_pull=pull, provider_pull=provider_pull)


class TestDecorationServiceTestCase(object):
    @pytest.fixture(autouse=True)
    def setup(self):
        mock_all_plans_and_tiers()

    @pytest.mark.django_db
    def test_decoration_type_basic_plan_upload_limit(
        self, enriched_pull, dbsession, mocker
    ):
        mocker.patch("services.license.is_enterprise", return_value=False)
        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        enriched_pull.database_pull.repository.owner.plan = "users-basic"
        enriched_pull.database_pull.repository.private = True

        commit = CommitFactory.create(
            repository=enriched_pull.database_pull.repository,
            author__service="github",
            timestamp=datetime.now(),
        )

        report = ReportFactory.create(
            commit=commit, report_type=ReportType.COVERAGE.value
        )
        for i in range(249):
            upload = UploadFactory.create(report=report, storage_path="url")
            dbsession.add(upload)
            insert_coverage_measurement(
                owner_id=enriched_pull.database_pull.repository.owner.ownerid,
                repo_id=enriched_pull.database_pull.repository.repoid,
                commit_id=commit.id,
                upload_id=upload.id,
                uploader_used=UploaderType.LEGACY.value,
                private_repo=enriched_pull.database_pull.repository.private,
                report_type=report.report_type,
            )
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        assert decoration_details.decoration_type != Decoration.upload_limit
        assert decoration_details.reason != "Org has exceeded the upload limit"

        upload = UploadFactory.create(report=report, storage_path="url")
        dbsession.add(upload)
        dbsession.flush()

        insert_coverage_measurement(
            owner_id=enriched_pull.database_pull.repository.owner.ownerid,
            repo_id=enriched_pull.database_pull.repository.repoid,
            commit_id=commit.id,
            upload_id=upload.id,
            uploader_used=UploaderType.LEGACY.value,
            private_repo=enriched_pull.database_pull.repository.private,
            report_type=report.report_type,
        )

        decoration_details = determine_decoration_details(enriched_pull)
        assert decoration_details.decoration_type == Decoration.upload_limit
        assert decoration_details.reason == "Org has exceeded the upload limit"

    @pytest.mark.django_db
    def test_decoration_type_team_plan_upload_limit(
        self, enriched_pull, dbsession, mocker
    ):
        mocker.patch("services.license.is_enterprise", return_value=False)
        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        enriched_pull.database_pull.repository.owner.plan = "users-teamm"
        enriched_pull.database_pull.repository.private = True

        commit = CommitFactory.create(
            repository=enriched_pull.database_pull.repository,
            author__service="github",
            timestamp=datetime.now(),
        )

        report = ReportFactory.create(
            commit=commit, report_type=ReportType.COVERAGE.value
        )
        for i in range(2499):
            upload = UploadFactory.create(report=report, storage_path="url")
            dbsession.add(upload)
            insert_coverage_measurement(
                owner_id=enriched_pull.database_pull.repository.owner.ownerid,
                repo_id=enriched_pull.database_pull.repository.repoid,
                commit_id=commit.id,
                upload_id=upload.id,
                uploader_used=UploaderType.LEGACY.value,
                private_repo=enriched_pull.database_pull.repository.private,
                report_type=report.report_type,
            )
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        assert decoration_details.decoration_type != Decoration.upload_limit
        assert decoration_details.reason != "Org has exceeded the upload limit"

        upload = UploadFactory.create(report=report, storage_path="url")
        dbsession.add(upload)
        dbsession.flush()
        insert_coverage_measurement(
            owner_id=enriched_pull.database_pull.repository.owner.ownerid,
            repo_id=enriched_pull.database_pull.repository.repoid,
            commit_id=commit.id,
            upload_id=upload.id,
            uploader_used=UploaderType.LEGACY.value,
            private_repo=enriched_pull.database_pull.repository.private,
            report_type=report.report_type,
        )

        decoration_details = determine_decoration_details(enriched_pull)
        assert decoration_details.decoration_type == Decoration.upload_limit
        assert decoration_details.reason == "Org has exceeded the upload limit"

    @pytest.mark.django_db
    def test_decoration_type_unlimited_upload_on_enterprise(
        self, enriched_pull, dbsession, mocker, mock_configuration
    ):
        mocker.patch("services.license.is_enterprise", return_value=True)
        encrypted_license = "wxWEJyYgIcFpi6nBSyKQZQeaQ9Eqpo3SXyUomAqQOzOFjdYB3A8fFM1rm+kOt2ehy9w95AzrQqrqfxi9HJIb2zLOMOB9tSy52OykVCzFtKPBNsXU/y5pQKOfV7iI3w9CHFh3tDwSwgjg8UsMXwQPOhrpvl2GdHpwEhFdaM2O3vY7iElFgZfk5D9E7qEnp+WysQwHKxDeKLI7jWCnBCBJLDjBJRSz0H7AfU55RQDqtTrnR+rsLDHOzJ80/VxwVYhb"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.mysite.com"
        )

        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        enriched_pull.database_pull.repository.owner.plan = "users-basic"
        enriched_pull.database_pull.repository.private = True

        commit = CommitFactory.create(
            repository=enriched_pull.database_pull.repository,
            author__service="github",
            timestamp=datetime.now(),
        )

        report = ReportFactory.create(commit=commit)
        for i in range(250):
            upload = UploadFactory.create(report=report, storage_path="url")
            dbsession.add(upload)
            insert_coverage_measurement(
                owner_id=enriched_pull.database_pull.repository.owner.ownerid,
                repo_id=enriched_pull.database_pull.repository.repoid,
                commit_id=commit.id,
                upload_id=upload.id,
                uploader_used=UploaderType.LEGACY.value,
                private_repo=enriched_pull.database_pull.repository.private,
                report_type=report.report_type,
            )
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        # self-hosted should not be limited with their uploads
        assert decoration_details.decoration_type != Decoration.upload_limit
        assert decoration_details.reason != "Org has exceeded the upload limit"

    @pytest.mark.django_db
    def test_uploads_used_with_expired_trial(self, mocker):
        owner = DjangoOwnerFactory(
            service="github",
            trial_status=TrialStatus.EXPIRED.value,
            trial_start_date=datetime.now() + timedelta(days=-10),
            trial_end_date=datetime.now() + timedelta(days=-2),
            plan=PlanName.BASIC_PLAN_NAME.value,
        )
        repository = DjangoRepositoryFactory(
            author=owner,
            private=True,
        )
        commit = DjangoCommitFactory(
            repository=repository,
            author__service="github",
            timestamp=datetime.now(),
        )
        report = CommitReportFactory(
            commit=commit, report_type=ReportType.COVERAGE.value
        )

        report_before_trial = DjangoUploadFactory(report=report, storage_path="url")
        report_before_trial.created_at += timedelta(days=-12)
        report_before_trial.save()
        upload_before_trial = insert_coverage_measurement(
            owner_id=owner.ownerid,
            repo_id=repository.repoid,
            commit_id=commit.id,
            upload_id=report_before_trial.id,
            uploader_used=UploaderType.LEGACY.value,
            private_repo=repository.private,
            report_type=report.report_type,
        )
        upload_before_trial.created_at += timedelta(days=-12)
        upload_before_trial.save()

        report_during_trial = DjangoUploadFactory(report=report, storage_path="url")
        report_during_trial.created_at += timedelta(days=-5)
        report_during_trial.save()
        upload_during_trial = insert_coverage_measurement(
            owner_id=owner.ownerid,
            repo_id=repository.repoid,
            commit_id=commit.id,
            upload_id=report_during_trial.id,
            uploader_used=UploaderType.LEGACY.value,
            private_repo=repository.private,
            report_type=report.report_type,
        )
        upload_during_trial.created_at += timedelta(days=-5)
        upload_during_trial.save()

        report_after_trial = DjangoUploadFactory(report=report, storage_path="url")
        insert_coverage_measurement(
            owner_id=owner.ownerid,
            repo_id=repository.repoid,
            commit_id=commit.id,
            upload_id=report_after_trial.id,
            uploader_used=UploaderType.LEGACY.value,
            private_repo=repository.private,
            report_type=report.report_type,
        )

        uploads_present = ReportSession.objects.all()
        assert len(uploads_present) == 3

        mock_config_helper(mocker, configs={"setup.upload_throttling_enabled": True})
        plan_service = PlanService(current_org=owner)
        uploads_used = determine_uploads_used(plan_service=plan_service)

        assert uploads_used == 2

    @pytest.mark.django_db
    def test_get_decoration_type_no_pull(self, mocker):
        decoration_details = determine_decoration_details(None)

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "No pull"
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_no_provider_pull(self, mocker, enriched_pull):
        enriched_pull.provider_pull = None

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.standard
        assert (
            decoration_details.reason
            == "Can't determine PR author - no pull info from provider"
        )
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_public_repo(self, dbsession, mocker, enriched_pull):
        enriched_pull.database_pull.repository.private = False
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "Public repo"
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_not_pr_plan(self, dbsession, mocker, enriched_pull):
        enriched_pull.database_pull.repository.owner.plan = "users-inappm"
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "Org not on PR plan"
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    # what is a users plan?
    def test_get_decoration_type_for_users_plan(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username="drazisil-org",
            owner__service="github",
            owner__unencrypted_oauth_token="testtfasdfasdflxuu2kfer2ef23",
            owner__plan=PlanName.BASIC_PLAN_NAME.value,
            private=True,
        )
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(
            repository=repository,
            author__service="github",
        )
        head_commit = CommitFactory.create(
            repository=repository,
            author__service="github",
        )
        pull = PullFactory.create(
            author__service="github",
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
            state="merged",
        )
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        provider_pull = {
            "author": {"id": "7123", "username": "tomcat"},
            "base": {
                "branch": "master",
                "commitid": "b92edba44fdd29fcc506317cc3ddeae1a723dd08",
            },
            "head": {
                "branch": "reason/some-testing",
                "commitid": "a06aef4356ca35b34c5486269585288489e578db",
            },
            "number": "1",
            "id": "1",
            "state": "open",
            "title": "Creating new code for reasons no one knows",
        }
        enriched_pull_whitelisted = EnrichedPull(
            database_pull=pull, provider_pull=provider_pull
        )

        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull_whitelisted.provider_pull["author"]["username"],
            service_id=enriched_pull_whitelisted.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull_whitelisted)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be manually activated"
        assert decoration_details.should_attempt_author_auto_activation is False
        assert (
            pr_author.ownerid
            not in enriched_pull_whitelisted.database_pull.repository.owner.plan_activated_users
        )

    @pytest.mark.django_db
    def test_get_decoration_type_pr_author_not_in_db(self, mocker, enriched_pull):
        enriched_pull.provider_pull["author"]["id"] = "190"

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "PR author not found in database"
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_pr_author_manual_activation_required(
        self, dbsession, mocker, enriched_pull, with_sql_functions
    ):
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = False

        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be manually activated"
        assert decoration_details.should_attempt_author_auto_activation is False
        assert (
            pr_author.ownerid
            not in enriched_pull.database_pull.repository.owner.plan_activated_users
        )

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "is_bot,param,value",
        [
            (True, "email", "dependabot[bot]@users.noreply.github.com"),
            (True, "email", "29139614+renovate[bot]@users.noreply.github.com"),
            (True, "service_id", "29139614"),
            (False, None, None),
        ],
    )
    def test_is_bot_account(self, is_bot, param, value):
        pr_author = OwnerFactory.create(
            service="github",
        )
        if is_bot and param == "email":
            pr_author.email = value
        elif is_bot and param == "service_id":
            pr_author.service_id = value
        assert _is_bot_account(pr_author) == is_bot

    @pytest.mark.django_db
    def test_get_decoration_type_bot(self, dbsession, mocker, enriched_pull):
        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            email=BOT_USER_EMAILS[0],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.standard
        assert (
            decoration_details.reason
            == "Bot user detected (does not need to be activated)"
        )
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_pr_author_already_active(
        self, dbsession, mocker, enriched_pull
    ):
        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = [
            pr_author.ownerid
        ]
        enriched_pull.database_pull.repository.owner.plan_auto_activate = False
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "User is currently activated"
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_should_attempt_pr_author_auto_activation(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be activated"
        assert decoration_details.should_attempt_author_auto_activation is True
        assert (
            decoration_details.activation_org_ownerid
            == enriched_pull.database_pull.repository.owner.ownerid
        )
        assert decoration_details.activation_author_ownerid == pr_author.ownerid
        # activation hasnt happened yet
        assert (
            pr_author.ownerid
            not in enriched_pull.database_pull.repository.owner.plan_activated_users
        )

    @pytest.mark.django_db
    def test_get_decoration_type_should_attempt_pr_author_auto_activation_users_free(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.owner.plan = "users-free"
        enriched_pull.database_pull.repository.owner.plan_user_count = 5
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be activated"
        assert decoration_details.should_attempt_author_auto_activation is True
        assert (
            decoration_details.activation_org_ownerid
            == enriched_pull.database_pull.repository.owner.ownerid
        )
        assert decoration_details.activation_author_ownerid == pr_author.ownerid
        # activation hasnt happened yet
        assert (
            pr_author.ownerid
            not in enriched_pull.database_pull.repository.owner.plan_activated_users
        )

    @pytest.mark.django_db
    def test_get_decoration_type_passing_empty_upload(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.private = False
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull, "pass")

        assert decoration_details.decoration_type == Decoration.passing_empty_upload
        assert decoration_details.reason == "Non testable files got changed."
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_failing_empty_upload(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.private = False
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull, "fail")

        assert decoration_details.decoration_type == Decoration.failing_empty_upload
        assert decoration_details.reason == "Testable files got changed."
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_processing_upload(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.private = False
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull, "processing")

        assert decoration_details.decoration_type == Decoration.processing_upload
        assert decoration_details.reason == "Upload is still processing."
        assert decoration_details.should_attempt_author_auto_activation is False


class TestDecorationServiceGitLabTestCase(object):
    @pytest.fixture(autouse=True)
    def setup(self):
        mock_all_plans_and_tiers()

    @pytest.mark.django_db
    def test_get_decoration_type_not_pr_plan_gitlab_subgroup(
        self,
        dbsession,
        mocker,
        gitlab_root_group,
        gitlab_enriched_pull_subgroup,
        with_sql_functions,
    ):
        gitlab_root_group.plan = "users-inappm"
        dbsession.flush()

        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "Org not on PR plan"
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_pr_author_not_in_db_gitlab_subgroup(
        self,
        mocker,
        gitlab_root_group,
        gitlab_enriched_pull_subgroup,
        with_sql_functions,
    ):
        gitlab_enriched_pull_subgroup.provider_pull["author"]["id"] = "190"

        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "PR author not found in database"
        assert decoration_details.should_attempt_author_auto_activation is False

    @pytest.mark.django_db
    def test_get_decoration_type_pr_author_manual_activation_required_gitlab_subgroup(
        self,
        dbsession,
        mocker,
        gitlab_root_group,
        gitlab_enriched_pull_subgroup,
        with_sql_functions,
    ):
        gitlab_root_group.plan_auto_activate = False
        # setting on child group should not matter, uses setting from root
        child_group = gitlab_enriched_pull_subgroup.database_pull.repository.owner
        child_group.plan_auto_activate = True

        pr_author = OwnerFactory.create(
            username=gitlab_enriched_pull_subgroup.provider_pull["author"]["username"],
            service="gitlab",
            service_id=gitlab_enriched_pull_subgroup.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be manually activated"
        assert decoration_details.should_attempt_author_auto_activation is False
        assert decoration_details.activation_org_ownerid is None
        assert decoration_details.activation_author_ownerid is None

        # allow auto-activate on root
        gitlab_root_group.plan_auto_activate = True
        # setting on child group should not matter, uses setting from root
        child_group.plan_auto_activate = False
        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be activated"
        assert decoration_details.should_attempt_author_auto_activation is True
        assert decoration_details.activation_org_ownerid == gitlab_root_group.ownerid
        assert decoration_details.activation_author_ownerid == pr_author.ownerid
        # activation hasn't happened yet
        assert pr_author.ownerid not in gitlab_root_group.plan_activated_users

    @pytest.mark.django_db
    def test_get_decoration_type_pr_author_already_active_subgroup(
        self,
        dbsession,
        mocker,
        gitlab_root_group,
        gitlab_enriched_pull_subgroup,
        with_sql_functions,
    ):
        pr_author = OwnerFactory.create(
            username=gitlab_enriched_pull_subgroup.provider_pull["author"]["username"],
            service="gitlab",
            service_id=gitlab_enriched_pull_subgroup.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()
        gitlab_root_group.plan_activated_users = [pr_author.ownerid]
        gitlab_root_group.plan_auto_activate = False
        dbsession.flush()

        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "User is currently activated"
        assert decoration_details.should_attempt_author_auto_activation is False
        assert decoration_details.activation_org_ownerid is None
        assert decoration_details.activation_author_ownerid is None

    @pytest.mark.django_db
    def test_get_decoration_type_should_attempt_pr_author_auto_activation(
        self,
        dbsession,
        mocker,
        gitlab_root_group,
        gitlab_enriched_pull_subgroup,
        with_sql_functions,
    ):
        pr_author = OwnerFactory.create(
            username=gitlab_enriched_pull_subgroup.provider_pull["author"]["username"],
            service="gitlab",
            service_id=gitlab_enriched_pull_subgroup.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()
        gitlab_root_group.plan_user_count = 3
        gitlab_root_group.plan_activated_users = []
        gitlab_root_group.plan_auto_activate = True
        dbsession.flush()

        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be activated"
        assert decoration_details.should_attempt_author_auto_activation is True
        assert decoration_details.activation_org_ownerid == gitlab_root_group.ownerid
        assert decoration_details.activation_author_ownerid == pr_author.ownerid
        # activation hasn't happened yet
        assert pr_author.ownerid not in gitlab_root_group.plan_activated_users

    @pytest.mark.django_db
    def test_get_decoration_type_owner_activated_users_null(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = None
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
            service="github",
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be activated"
        assert decoration_details.should_attempt_author_auto_activation is True
        assert (
            decoration_details.activation_org_ownerid
            == enriched_pull.database_pull.repository.owner.ownerid
        )
        assert decoration_details.activation_author_ownerid == pr_author.ownerid
        assert enriched_pull.database_pull.repository.owner.plan_activated_users is None

    @pytest.mark.django_db
    def test_uploads_used_with_expired_trial(self, mocker, dbsession):
        owner = DjangoOwnerFactory(
            service="gitlab",
            trial_status=TrialStatus.EXPIRED.value,
            trial_start_date=datetime.now() + timedelta(days=-10),
            trial_end_date=datetime.now() + timedelta(days=-2),
            plan=PlanName.BASIC_PLAN_NAME.value,
        )
        repository = DjangoRepositoryFactory(
            author=owner,
            private=True,
        )
        commit = DjangoCommitFactory(
            repository=repository,
            author__service="gitlab",
            timestamp=datetime.now(),
        )
        report = CommitReportFactory(
            commit=commit, report_type=ReportType.COVERAGE.value
        )
        DjangoUploadFactory(report=report, storage_path="url")
        DjangoUploadFactory(report=report, storage_path="url")

        uploads_present = ReportSession.objects.all()
        assert len(uploads_present) == 2

        mock_config_helper(mocker, configs={"setup.upload_throttling_enabled": False})
        plan_service = PlanService(current_org=owner)
        uploads_used = determine_uploads_used(plan_service=plan_service)

        assert uploads_used == 0

    @pytest.mark.django_db
    def test_author_is_activated_on_subgroup_not_root(
        self, dbsession, gitlab_root_group, gitlab_enriched_pull_subgroup
    ):
        pr_author = OwnerFactory.create(
            username=gitlab_enriched_pull_subgroup.provider_pull["author"]["username"],
            service="gitlab",
            service_id=gitlab_enriched_pull_subgroup.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        # user is activated on subgroup but not root group and root group does not auto activate
        gitlab_root_group.plan_auto_activate = False
        child_group = gitlab_enriched_pull_subgroup.database_pull.repository.owner
        child_group.plan_auto_activate = False
        child_group.plan_activated_users = [pr_author.ownerid]
        dbsession.flush()

        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be manually activated"
        assert decoration_details.should_attempt_author_auto_activation is False
        assert decoration_details.activation_org_ownerid is None
        assert decoration_details.activation_author_ownerid is None

        assert pr_author.ownerid not in gitlab_root_group.plan_activated_users
        assert (
            pr_author.ownerid
            in gitlab_enriched_pull_subgroup.database_pull.repository.owner.plan_activated_users
        )

        # allow auto-activate on root for user to get non-blocking decoration
        gitlab_root_group.plan_auto_activate = True
        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "User must be activated"
        assert decoration_details.should_attempt_author_auto_activation is True
        assert decoration_details.activation_org_ownerid == gitlab_root_group.ownerid
        assert decoration_details.activation_author_ownerid == pr_author.ownerid
