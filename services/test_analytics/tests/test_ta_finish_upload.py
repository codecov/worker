from datetime import datetime, timedelta
from typing import Literal
from unittest.mock import call

import pytest
from django.db import transaction as django_transaction
from shared.django_apps.core.models import Commit as DjangoCommit
from shared.django_apps.core.models import Repository as DjangoRepo
from shared.django_apps.reports.tests.factories import (
    UploadErrorFactory as DjangoUploadErrorFactory,
)
from shared.django_apps.reports.tests.factories import (
    UploadFactory as DjangoUploadFactory,
)
from shared.django_apps.ta_timeseries.tests.factories import TestrunFactory
from shared.django_apps.test_analytics.models import Flake

from database.enums import ReportType
from database.tests.factories import (
    PullFactory,
    UploadFactory,
)
from services.test_analytics.ta_finish_upload import FinisherResult, new_impl
from services.yaml import UserYaml
from tests.helpers import mock_all_plans_and_tiers


@pytest.fixture
def mock_repo_provider_comments(mocker):
    m = mocker.MagicMock(
        edit_comment=mocker.AsyncMock(return_value=True),
        post_comment=mocker.AsyncMock(return_value={"id": 1}),
    )
    _ = mocker.patch(
        "helpers.notifier.get_repo_provider_service",
        return_value=m,
    )
    _ = mocker.patch(
        "services.test_analytics.ta_finish_upload.get_repo_provider_service",
        return_value=m,
    )
    return m


@pytest.fixture
@pytest.mark.django_db(databases=["default", "ta_timeseries"], transaction=True)
def prepopulate(dbsession):
    django_upload = DjangoUploadFactory(
        report__report_type=ReportType.TEST_RESULTS.value,
        report__commit__branch="main",
        report__commit__merged=True,
        report__commit__repository__branch="main",
        report__commit__repository__private=False,
    )
    django_upload.save()

    testrun = TestrunFactory(
        repo_id=django_upload.report.commit.repository.repoid,
        commit_sha=django_upload.report.commit.commitid,
        upload_id=django_upload.id,
        outcome="pass",
        test_id=b"test-id",
        duration_seconds=100.0,
    )
    testrun.save()
    django_transaction.commit()

    django_repo = DjangoRepo.objects.get(
        repoid=django_upload.report.commit.repository.repoid
    )
    django_commit = DjangoCommit.objects.get(
        commitid=django_upload.report.commit.commitid
    )

    sql_alc_upload = UploadFactory(
        report__report_type=ReportType.TEST_RESULTS.value,
        report__commit__commitid=django_commit.commitid,
        report__commit__branch=django_commit.branch,
        report__commit__merged=django_commit.merged,
        report__commit__repository__repoid=django_repo.repoid,
        report__commit__repository__private=django_repo.private,
        report__commit__repository__branch=django_repo.branch,
        report__commit__repository__name="test-repo",
        report__commit__repository__owner__service="github",
        report__commit__repository__owner__username="test-user",
    )
    dbsession.add(sql_alc_upload)
    dbsession.commit()

    return django_upload, sql_alc_upload, testrun


@pytest.mark.django_db(databases=["default", "ta_timeseries"], transaction=True)
def test_ta_finish_upload(
    mocker, dbsession, mock_repo_provider_comments, prepopulate, snapshot
):
    mock_all_plans_and_tiers()

    django_upload, sql_alc_upload, testrun = prepopulate
    repo = sql_alc_upload.report.commit.repository
    commit = sql_alc_upload.report.commit

    mock_send_task = mocker.patch(
        "services.test_analytics.ta_finish_upload.celery_app.send_task",
    )

    def run_task() -> FinisherResult:
        result = new_impl(
            db_session=dbsession,
            repo=repo,
            commit=commit,
            commit_yaml=commit_yaml,
            impl_type="new",
        )
        return result

    def mock_pull(pull: mocker.Mock | None):
        mocker.patch(
            "services.test_analytics.ta_finish_upload.fetch_and_update_pull_request_information_from_commit",
            return_value=pull,
        )

    def mock_seat(b: bool):
        mocker.patch(
            "services.test_analytics.ta_finish_upload.check_seat_activation",
            return_value=b,
        )

    def assert_result(attempted: bool, succeeded: bool, queued: bool):
        assert result == {
            "notify_attempted": attempted,
            "notify_succeeded": succeeded,
            "queue_notify": queued,
        }

    def assert_tasks(tasks: list[Literal["flakes", "cache_rollup"]]):
        assert mock_send_task.call_count == len(tasks)
        task_dict = {
            "flakes": call(
                "app.tasks.flakes.ProcessFlakesTask",
                kwargs={
                    "repo_id": repo.repoid,
                    "commit_id": commit.commitid,
                    "impl_type": "new",
                },
            ),
            "cache_rollup": call(
                "app.tasks.cache_rollup.CacheTestRollupsTask",
                kwargs={
                    "repoid": repo.repoid,
                    "branch": commit.branch,
                    "impl_type": "new",
                },
            ),
        }
        mock_send_task.assert_has_calls(
            [task_dict[task] for task in tasks],
        )
        mock_send_task.reset_mock()

    def assert_comment_snapshot():
        assert (
            snapshot("txt") == mock_repo_provider_comments.edit_comment.call_args[0][2]
        )
        mock_repo_provider_comments.edit_comment.reset_mock()

    # no comment
    commit_yaml = UserYaml({"comment": False})

    result = run_task()

    assert_result(False, False, False)
    assert_tasks(["flakes", "cache_rollup"])

    # no failures or errors
    commit_yaml = UserYaml({})

    commit.branch = None
    commit.merged = False
    dbsession.commit()

    result = run_task()

    assert_result(False, True, True)
    assert_tasks([])

    # no pull
    error = DjangoUploadErrorFactory(
        report_session=django_upload,
        error_code="file_not_in_storage",
        error_params={},
    )
    error.save()

    mock_pull(None)

    result = run_task()

    assert_result(False, False, False)
    assert_tasks([])

    # seat activation

    mock_pull(
        mocker.Mock(
            provider_pull={
                "author": {
                    "username": "test-user",
                },
            },
            database_pull=PullFactory(
                repository=repo,
                author=commit.repository.owner,
                commentid=1,
            ),
        )
    )

    _ = mock_seat(True)

    result = run_task()

    assert_result(False, True, False)
    assert_tasks([])
    assert_comment_snapshot()

    # only error

    _ = mock_seat(False)

    result = run_task()

    assert_result(True, False, True)
    assert_tasks([])
    assert_comment_snapshot()

    # no flake detection

    testrun.outcome = "failure"
    testrun.save()
    django_transaction.commit()

    result = run_task()

    assert_result(True, True, False)
    assert_tasks([])
    assert_comment_snapshot()

    # flake detection

    f = Flake(
        repoid=testrun.repo_id,
        test_id=testrun.test_id,
        start_date=datetime.now() - timedelta(days=1),
        end_date=None,
        recent_passes_count=0,
        count=10,
        fail_count=10,
    )
    f.save()
    django_transaction.commit()

    result = run_task()

    assert_result(True, True, False)
    assert_tasks([])
    assert_comment_snapshot()

    # no error

    error.delete()
    django_transaction.commit()

    result = run_task()

    assert_result(True, True, False)
    assert_tasks([])
    assert_comment_snapshot()
