import pytest

from database.tests.factories import CommitFactory
from tasks.bundle_analysis_notify import BundleAnalysisNotifyTask


@pytest.mark.asyncio
async def test_bundle_analysis_notify_task(
    mocker,
    dbsession,
    celery_app,
    mock_redis,
):
    mocker.patch.object(BundleAnalysisNotifyTask, "app", celery_app)

    commit = CommitFactory.create()
    dbsession.add(commit)
    dbsession.flush()

    mocker.patch("services.bundle_analysis.Notifier.notify", return_value=True)

    result = await BundleAnalysisNotifyTask().run_async(
        dbsession,
        {"results": [{"error": None}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
    )
    assert result == {
        "notify_attempted": True,
        "notify_succeeded": True,
    }
