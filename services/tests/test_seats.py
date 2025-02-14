import pytest
from shared.plan.constants import PlanName

from database.tests.factories import OwnerFactory, PullFactory
from services.repository import EnrichedPull
from services.seats import ShouldActivateSeat, determine_seat_activation
from tests.helpers import mock_all_plans_and_tiers


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


@pytest.mark.django_db
def test_seat_billing_plan(dbsession):
    mock_all_plans_and_tiers()
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = PlanName.CODECOV_PRO_MONTHLY_LEGACY.value
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.NO_ACTIVATE
    assert activate_seat_info.reason == "no_pr_billing_plan"


@pytest.mark.django_db
def test_seat_no_author(dbsession):
    mock_all_plans_and_tiers()
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = PlanName.CODECOV_PRO_MONTHLY.value
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={"author": {"id": "100", "username": "test_username"}},
    )
    activate_seat_info = determine_seat_activation(enriched_pull)

    assert activate_seat_info.should_activate_seat == ShouldActivateSeat.NO_ACTIVATE
    assert activate_seat_info.reason == "no_pr_author"


@pytest.mark.django_db
def test_seat_author_in_org(dbsession):
    mock_all_plans_and_tiers()
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = PlanName.CODECOV_PRO_MONTHLY.value
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


@pytest.mark.django_db
def test_seat_author_not_in_org(dbsession):
    mock_all_plans_and_tiers()
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = PlanName.CODECOV_PRO_MONTHLY.value
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


@pytest.mark.django_db
def test_seat_author_auto_activate(dbsession):
    mock_all_plans_and_tiers()
    pull = PullFactory()
    dbsession.add(pull)
    dbsession.flush()

    pull.repository.private = True
    pull.repository.owner.plan = PlanName.CODECOV_PRO_MONTHLY.value
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
