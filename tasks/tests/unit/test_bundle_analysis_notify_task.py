import pytest

from database.tests.factories import CommitFactory
from services.bundle_analysis.new_notify import BundleAnalysisNotifyReturn
from services.bundle_analysis.new_notify.types import NotificationType
from tasks.bundle_analysis_notify import BundleAnalysisNotifyTask


@pytest.mark.parametrize(
    "configured_notifications_count, successful_notifications_count, expected",
    [
        (0, 0, "nothing_to_notify"),
        (2, 2, "full_success"),
        (2, 1, "partial_success"),
    ],
)
def test_bundle_analysis_notify_task_get_success(
    configured_notifications_count, successful_notifications_count, expected
):
    task = BundleAnalysisNotifyTask()
    assert (
        task.get_success_value(
            configured_notifications_count, successful_notifications_count
        )
        == expected
    )


def test_bundle_analysis_notify_task(
    mocker,
    dbsession,
    celery_app,
    mock_redis,
):
    mocker.patch.object(BundleAnalysisNotifyTask, "app", celery_app)

    commit = CommitFactory.create()
    dbsession.add(commit)
    dbsession.flush()

    mocker.patch(
        "services.bundle_analysis.new_notify.BundleAnalysisNotifyService.notify",
        return_value=BundleAnalysisNotifyReturn(
            notifications_configured=(NotificationType.PR_COMMENT,),
            notifications_successful=(NotificationType.PR_COMMENT,),
        ),
    )

    result = BundleAnalysisNotifyTask().run_impl(
        dbsession,
        {"results": [{"error": None}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
    )
    assert result == {
        "notify_attempted": True,
        "notify_succeeded": "full_success",
    }
