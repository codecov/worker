from database.tests.factories import OwnerFactory, PullFactory
from services.billing import BillingPlan
from services.repository import EnrichedPull
from services.seats import ShouldActivateSeat, determine_seat_activation


def test_seat_provider_none(dbsession):
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull=None,
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.NO_ACTIVATE
    assert activate_seat_info.reason == "no_provider_pull"


def test_seat_repo_public(dbsession):
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = False
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.NO_ACTIVATE
    assert activate_seat_info.reason == "public_repo"


def test_seat_billing_plan(dbsession):
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = BillingPlan.users_monthly.value
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.NO_ACTIVATE
    assert activate_seat_info.reason == "no_pr_billing_plan"


def test_seat_no_author(dbsession):
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = BillingPlan.pr_monthly.value
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.NO_ACTIVATE
    assert activate_seat_info.reason == "no_pr_author"


def test_seat_author_in_org(dbsession):
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = BillingPlan.pr_monthly.value
    pull.repository.owner.service = "github"
    dbsession.flush()

    author = OwnerFactory(service="github", service_id=100)
    dbsession.add(author)
    dbsession.flush()

    pull.repository.owner.plan_activated_users = [author.ownerid]
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.NO_ACTIVATE
    assert activate_seat_info.reason == "author_in_plan_activated_users"


def test_seat_author_not_in_org(dbsession):
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = BillingPlan.pr_monthly.value
    pull.repository.owner.service = "github"
    dbsession.flush()

    author = OwnerFactory(service="github", service_id=100)
    dbsession.add(author)
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.MANUAL_ACTIVATE
    assert activate_seat_info.reason == "manual_activate"


def test_seat_author_auto_activate(dbsession):
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = BillingPlan.pr_monthly.value
    pull.repository.owner.plan_auto_activate = True
    pull.repository.owner.service = "github"
    dbsession.flush()

    author = OwnerFactory(service="github", service_id=100)
    dbsession.add(author)
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.AUTO_ACTIVATE
    assert activate_seat_info.reason == "auto_activate"
