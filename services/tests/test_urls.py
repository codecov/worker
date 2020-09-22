from database.tests.factories import PullFactory, RepositoryFactory, OwnerFactory
from services.urls import get_pull_url
import os


def test_get_pull_url_returns_new_compare_url_for_whitelisted_owners(
):
    owner = OwnerFactory.create(ownerid=10)

    os.environ["NEW_COMPARE_WHITELISTED_OWNERS"] = f"{owner.ownerid}, 55, 34"

    repo = RepositoryFactory.create(owner=owner)
    pull = PullFactory.create(repository=repo)
    assert get_pull_url(pull) == f"https://app.codecov.io/gh/{owner.username}/{repo.name}/compare/{pull.pullid}"
