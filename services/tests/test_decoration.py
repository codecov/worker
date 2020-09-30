import pytest

from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from services.decoration import Decoration, determine_decoration_details
from services.repository import EnrichedPull


@pytest.fixture
def enriched_pull(dbsession):
    repository = RepositoryFactory.create(
        owner__username="codecov",
        owner__unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        owner__plan="users-pr-inappm",
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


@pytest.fixture
def gitlab_root_group(dbsession):
    root_group = OwnerFactory.create(
        username="root_group",
        service="gitlab",
        unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        plan="users-pr-inappm",
        plan_activated_users=[],
    )
    dbsession.add(root_group)
    dbsession.flush()
    return root_group


@pytest.fixture
def gitlab_enriched_pull_subgroup(dbsession, gitlab_root_group):
    subgroup = OwnerFactory.create(
        username="subgroup",
        service="gitlab",
        unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        plan=None,
        parent_service_id=gitlab_root_group.service_id,
    )
    dbsession.add(subgroup)
    dbsession.flush()

    repository = RepositoryFactory.create(
        owner=subgroup, name="example-python", image_token="abcdefghij", private=True,
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
    def test_get_decoration_type_no_pull(self, mocker):
        decoration_details = determine_decoration_details(None)

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "No pull"
        assert decoration_details.should_attempt_author_auto_activation is False

    def test_get_decoration_type_no_provider_pull(self, mocker, enriched_pull):
        enriched_pull.provider_pull = None

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.standard
        assert (
            decoration_details.reason
            == "Can't determine PR author - no pull info from provider"
        )
        assert decoration_details.should_attempt_author_auto_activation is False

    def test_get_decoration_type_public_repo(self, dbsession, mocker, enriched_pull):
        enriched_pull.database_pull.repository.private = False
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "Public repo"
        assert decoration_details.should_attempt_author_auto_activation is False

    def test_get_decoration_type_not_pr_plan(self, dbsession, mocker, enriched_pull):
        enriched_pull.database_pull.repository.owner.plan = "users-inappm"
        dbsession.flush()

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "Org not on PR plan"
        assert decoration_details.should_attempt_author_auto_activation is False

    def test_get_decoration_type_pr_author_not_in_db(self, mocker, enriched_pull):
        enriched_pull.provider_pull["author"]["id"] = "190"

        decoration_details = determine_decoration_details(enriched_pull)

        assert decoration_details.decoration_type == Decoration.upgrade
        assert decoration_details.reason == "PR author not found in database"
        assert decoration_details.should_attempt_author_auto_activation is False

    def test_get_decoration_type_pr_author_manual_activation_required(
        self, dbsession, mocker, enriched_pull, with_sql_functions
    ):
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = False

        pr_author = OwnerFactory.create(
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

    def test_get_decoration_type_pr_author_already_active(
        self, dbsession, mocker, enriched_pull
    ):
        pr_author = OwnerFactory.create(
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

    def test_get_decoration_type_should_attempt_pr_author_auto_activation(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
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

    def test_get_decoration_type_should_attempt_pr_author_auto_activation_users_free(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.owner.plan = "users-free"
        enriched_pull.database_pull.repository.owner.plan_user_count = 5
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
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


class TestDecorationServiceGitLabTestCase(object):
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

    def test_get_decoration_type_pr_author_manual_activation_required_gitlab_subgroup(
        self,
        dbsession,
        mocker,
        gitlab_root_group,
        gitlab_enriched_pull_subgroup,
        with_sql_functions,
    ):
        gitlab_root_group.plan_user_count = 3
        gitlab_root_group.plan_activated_users = []
        gitlab_root_group.plan_auto_activate = False

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

        assert pr_author.ownerid not in gitlab_root_group.plan_activated_users
        # shouldn't be in subgroup plan_activated_users either
        assert (
            pr_author.ownerid
            not in gitlab_enriched_pull_subgroup.database_pull.repository.owner.plan_activated_users
        )

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
        gitlab_root_group.plan_user_count = 3
        gitlab_root_group.plan_activated_users = [pr_author.ownerid]
        gitlab_root_group.plan_auto_activate = False
        dbsession.flush()

        decoration_details = determine_decoration_details(gitlab_enriched_pull_subgroup)
        dbsession.commit()

        assert decoration_details.decoration_type == Decoration.standard
        assert decoration_details.reason == "User is currently activated"
        assert decoration_details.should_attempt_author_auto_activation is False

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
        # activation hasnt happened yet
        assert pr_author.ownerid not in gitlab_root_group.plan_activated_users

    def test_get_decoration_type_owner_activated_users_null(
        self, dbsession, mocker, enriched_pull
    ):
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = None
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
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
