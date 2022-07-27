import pytest

from database.tests.factories import CommitFactory
from tasks.commit_update import CommitUpdateTask


@pytest.mark.integration
class TestCommitUpdate(object):
    @pytest.mark.asyncio
    async def test_update_commit(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_redis,
        celery_app,
    ):
        mocker.patch.object(CommitUpdateTask, "app", celery_app)

        commit = CommitFactory.create(
            message="",
            commitid="a2d3e3c30547a000f026daa47610bb3f7b63aece",
            repository__owner__unencrypted_oauth_token="ghp_test3c8iyfspq6h4s9ugpmq19qp7826rv20o",
            repository__owner__username="test-acc9",
            repository__owner__service="github",
            repository__owner__service_id="104562106",
            repository__name="test_example",
        )
        dbsession.add(commit)
        dbsession.flush()

        result = await CommitUpdateTask().run_async(
            dbsession, commit.repoid, commit.commitid
        )
        expected_result = {"was_updated": True}
        assert expected_result == result
        assert commit.message == "random-commit-msg"
        assert commit.parent_commit_id is None
        assert commit.branch == "featureA"
        assert commit.pullid == 1
