import os
import pytest

from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from services.decoration import (
    Decoration,
    get_decoration_type_and_reason,
    is_whitelisted,
)
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
def with_sql_functions(dbsession):
    dbsession.execute(
        """CREATE FUNCTION array_append_unique(anyarray, anyelement) RETURNS anyarray
                LANGUAGE sql IMMUTABLE
                AS $_$
            select case when $2 is null
                    then $1
                    else array_remove($1, $2) || array[$2]
                    end;
            $_$;"""
    )
    dbsession.execute(
        """create or replace function try_to_auto_activate(int, int) returns boolean as $$
            update owners
            set plan_activated_users = (
                case when coalesce(array_length(plan_activated_users, 1), 0) < plan_user_count  -- we have credits
                    then array_append_unique(plan_activated_users, $2)  -- add user
                    else plan_activated_users
                    end)
            where ownerid=$1
            returning (plan_activated_users @> array[$2]);
            $$ language sql volatile strict;"""
    )
    dbsession.flush()


class TestDecorationServiceTestCase(object):
    def test_whitelist(self, mocker):
        whitelist = "123 456  999"
        mocker.patch.dict(
            os.environ, {"PR_AUTHOR_BILLING_WHITELISTED_OWNERS": whitelist}
        )
        assert is_whitelisted(123) is True
        assert is_whitelisted(999) is True
        assert is_whitelisted(404) is False

    def test_get_decoration_type_no_pull(self, mocker):
        mocker.patch("services.decoration.is_whitelisted", return_value=True)

        decoration_type, reason = get_decoration_type_and_reason(None)

        assert decoration_type == Decoration.standard
        assert reason == "No pull"

    def test_get_decoration_type_no_provider_pull(self, mocker, enriched_pull):
        mocker.patch("services.decoration.is_whitelisted", return_value=True)
        enriched_pull.provider_pull = None

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)

        assert decoration_type == Decoration.standard
        assert reason == "Can't determine PR author - no pull info from provider"

    def test_get_decoration_type_public_repo(self, dbsession, mocker, enriched_pull):
        enriched_pull.database_pull.repository.private = False
        dbsession.flush()

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)

        assert decoration_type == Decoration.standard
        assert reason == "Public repo"

    def test_get_decoration_type_not_pr_plan(self, dbsession, mocker, enriched_pull):
        enriched_pull.database_pull.repository.owner.plan = "users-inappm"
        dbsession.flush()

        mocker.patch("services.decoration.is_whitelisted", return_value=True)

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)

        assert decoration_type == Decoration.standard
        assert reason == "Org not on PR plan"

    def test_get_decoration_type_not_in_whitelist(self, mocker, enriched_pull):
        mocker.patch("services.decoration.is_whitelisted", return_value=False)

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)

        assert decoration_type == Decoration.standard
        assert reason == "Org not in whitelist"

    def test_get_decoration_type_pr_author_not_in_db(self, mocker, enriched_pull):
        mocker.patch("services.decoration.is_whitelisted", return_value=True)
        enriched_pull.provider_pull["author"]["id"] = "190"

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)

        assert decoration_type == Decoration.upgrade
        assert reason == "PR author not found in database"

    def test_get_decoration_type_pr_author_auto_activate_success(
        self, dbsession, mocker, enriched_pull, with_sql_functions
    ):
        mocker.patch("services.decoration.is_whitelisted", return_value=True)
        enriched_pull.database_pull.repository.owner.plan_user_count = 10
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)
        dbsession.commit()

        assert decoration_type == Decoration.standard
        assert reason == "PR author auto activation success"
        assert enriched_pull.database_pull.repository.owner.plan_activated_users == [
            pr_author.ownerid
        ]

    def test_get_decoration_type_pr_author_auto_activate_failure(
        self, dbsession, mocker, enriched_pull, with_sql_functions
    ):
        mocker.patch("services.decoration.is_whitelisted", return_value=True)
        # already at max user count
        existing_activated_users = [1234, 5678, 9012]
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = (
            existing_activated_users
        )
        enriched_pull.database_pull.repository.owner.plan_auto_activate = True

        pr_author = OwnerFactory.create(
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)
        dbsession.commit()

        assert decoration_type == Decoration.upgrade
        assert reason == "PR author auto activation failed"
        assert (
            pr_author.ownerid
            not in enriched_pull.database_pull.repository.owner.plan_activated_users
        )
        assert (
            enriched_pull.database_pull.repository.owner.plan_activated_users
            == existing_activated_users
        )

    def test_get_decoration_type_pr_author_manual_activation_required(
        self, dbsession, mocker, enriched_pull, with_sql_functions
    ):
        mocker.patch("services.decoration.is_whitelisted", return_value=True)
        enriched_pull.database_pull.repository.owner.plan_user_count = 3
        enriched_pull.database_pull.repository.owner.plan_activated_users = []
        enriched_pull.database_pull.repository.owner.plan_auto_activate = False

        pr_author = OwnerFactory.create(
            username=enriched_pull.provider_pull["author"]["username"],
            service_id=enriched_pull.provider_pull["author"]["id"],
        )
        dbsession.add(pr_author)
        dbsession.flush()

        decoration_type, reason = get_decoration_type_and_reason(enriched_pull)
        dbsession.commit()

        assert decoration_type == Decoration.upgrade
        assert reason == "User must be manually activated"
        assert (
            pr_author.ownerid
            not in enriched_pull.database_pull.repository.owner.plan_activated_users
        )
