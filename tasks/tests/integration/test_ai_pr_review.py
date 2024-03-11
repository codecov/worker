import pytest

from database.tests.factories import OwnerFactory, RepositoryFactory
from tasks.ai_pr_review import AiPrReviewTask


@pytest.mark.integration
def test_ai_pr_review_task(
    mocker,
    dbsession,
):
    owner = OwnerFactory(service="github")
    repository = RepositoryFactory(owner=owner)
    dbsession.add(owner)
    dbsession.add(repository)
    dbsession.flush()

    perform_review = mocker.patch("tasks.ai_pr_review.perform_review")

    task = AiPrReviewTask()

    result = task.run_impl(
        dbsession,
        repoid=repository.repoid,
        pullid=123,
    )

    assert result == {"successful": True}
    perform_review.assert_called_once_with(repository, 123)
