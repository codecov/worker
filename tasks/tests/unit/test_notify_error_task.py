import pytest
from mock import AsyncMock
from shared.torngit.exceptions import TorngitClientError

from database.tests.factories import (
    CommitFactory,
    PullFactory,
    ReportFactory,
    RepositoryFactory,
    UploadFactory,
)
from services.repository import EnrichedPull
from tasks.notify_error import ErrorNotifier, NotifyErrorTask


@pytest.fixture
def mock_repo_provider_comments(mocker):
    m = mocker.MagicMock(
        edit_comment=AsyncMock(return_value=True),
        post_comment=AsyncMock(return_value={"id": 1}),
    )
    _ = mocker.patch(
        "helpers.notifier.get_repo_provider_service",
        return_value=m,
    )
    return m


def test_error_notifier():
    commit = CommitFactory()
    failed_upload = 1
    total_upload = 2

    e = ErrorNotifier(commit, None, failed_upload, total_upload)

    assert (
        e.build_message()
        == f"❗️ We couldn't process [{failed_upload}] out of [{total_upload}] uploads. Codecov cannot generate a coverage report with partially processed data. Please review the upload errors on the commit page."
    )


def test_notify_error_task(mocker, dbsession, mock_repo_provider_comments):
    repo = RepositoryFactory()
    dbsession.add(repo)
    commit = CommitFactory(repository=repo)
    dbsession.add(commit)
    report = ReportFactory(commit=commit)
    dbsession.add(report)
    upload1 = UploadFactory(report=report, state="complete")
    upload2 = UploadFactory(report=report, state="error")
    dbsession.add(upload1)
    dbsession.add(upload2)
    dbsession.flush()

    pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

    _ = mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=EnrichedPull(
            database_pull=pull,
            provider_pull={},
        ),
    )

    result = NotifyErrorTask().run_impl(
        dbsession,
        commitid=commit.commitid,
        repoid=commit.repoid,
        current_yaml={},
    )

    assert result["success"] == True


def test_notify_error_task_failure(mocker, dbsession, mock_repo_provider_comments):
    mock_repo_provider_comments.post_comment.side_effect = TorngitClientError

    repo = RepositoryFactory()
    dbsession.add(repo)
    commit = CommitFactory(repository=repo)
    dbsession.add(commit)
    report = ReportFactory(commit=commit)
    dbsession.add(report)
    upload1 = UploadFactory(report=report, state="complete")
    upload2 = UploadFactory(report=report, state="error")
    dbsession.add(upload1)
    dbsession.add(upload2)
    dbsession.flush()

    pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

    _ = mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=EnrichedPull(
            database_pull=pull,
            provider_pull={},
        ),
    )

    result = NotifyErrorTask().run_impl(
        dbsession,
        commitid=commit.commitid,
        repoid=commit.repoid,
        current_yaml={},
    )
    print(result)
    assert result["success"] == False
