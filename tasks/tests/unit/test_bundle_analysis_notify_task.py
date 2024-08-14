from database.tests.factories import CommitFactory
from services.bundle_analysis.new_notify import BundleAnalysisNotifyReturn
from services.bundle_analysis.new_notify.types import (
    NotificationSuccess,
    NotificationType,
)
from tasks.bundle_analysis_notify import BundleAnalysisNotifyTask


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
        "notify_succeeded": NotificationSuccess.FULL_SUCCESS,
    }


def test_bundle_analysis_notify_skips_if_all_processing_fail(dbsession):
    commit = CommitFactory.create()
    dbsession.add(commit)
    dbsession.flush()
    result = BundleAnalysisNotifyTask().run_impl(
        dbsession,
        {"results": [{"error": True}]},
        repoid=commit.repoid,
        commitid=commit.commitid,
        commit_yaml={},
    )
    assert result == {
        "notify_attempted": False,
        "notify_succeeded": NotificationSuccess.ALL_ERRORED,
    }
