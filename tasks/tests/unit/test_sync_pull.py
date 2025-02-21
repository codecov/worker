import json
import os
from pathlib import Path

import pytest
from celery.exceptions import Retry
from mock.mock import MagicMock
from redis.exceptions import LockError
from shared.reports.types import Change
from shared.torngit.exceptions import TorngitClientError

from database.models import Commit, Pull, Repository
from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from database.tests.factories.reports import TestFactory
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from services.repository import EnrichedPull
from services.yaml import UserYaml
from tasks.sync_pull import PullSyncTask
from tests.helpers import mock_all_plans_and_tiers

here = Path(__file__)


@pytest.fixture
def repository(dbsession) -> Repository:
    repository = RepositoryFactory.create(owner__plan="users-inappm")
    dbsession.add(repository)
    dbsession.flush()
    return repository


@pytest.fixture
def base_commit(dbsession, repository) -> Commit:
    commit = CommitFactory.create(repository=repository)
    dbsession.add(commit)
    dbsession.flush()
    return commit


@pytest.fixture
def head_commit(dbsession, repository) -> Commit:
    commit = CommitFactory.create(repository=repository)
    dbsession.add(commit)
    dbsession.flush()
    return commit


@pytest.fixture
def pull(dbsession, repository, base_commit, head_commit) -> Pull:
    pull = PullFactory.create(
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
    )
    dbsession.add(pull)
    dbsession.flush()
    return pull


@pytest.mark.parametrize(
    "tests_exist",
    [True, False],
)
@pytest.mark.django_db
def test_update_pull_commits_merged(
    dbsession,
    mocker,
    tests_exist,
    repository,
    head_commit,
    base_commit,
    pull,
):
    mock_all_plans_and_tiers()

    pull.state = "merged"
    pullid = pull.pullid
    base_commit.pullid = pullid
    head_commit.pullid = pullid
    first_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    second_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    third_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    fourth_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    dbsession.add(pull)
    dbsession.add(first_commit)
    dbsession.add(second_commit)
    dbsession.add(third_commit)
    dbsession.add(fourth_commit)
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.flush()
    task = PullSyncTask()
    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull=dict(base=dict(branch="lookatthis"), head=dict(branch="thing")),
    )
    commits = [first_commit.commitid, third_commit.commitid]
    commits_at_base = {
        "commitid": first_commit.commitid,
        "parents": [{"commitid": third_commit.commitid, "parents": []}],
    }

    apply_async: MagicMock = mocker.patch.object(
        task.app.tasks["app.tasks.flakes.ProcessFlakesTask"], "apply_async"
    )

    current_yaml = UserYaml.from_dict(
        {
            "test_analytics": {
                "flake_detection": True,
            }
        }
    )
    mock_repo_provider = MagicMock(
        get_commit=MagicMock(return_value=dict(parents=["1", "2"]))
    )
    res = task.update_pull_commits(
        mock_repo_provider,
        enriched_pull,
        commits,
        commits_at_base,
        current_yaml,
        repository,
    )

    apply_async.assert_called_once_with(
        kwargs=dict(
            repo_id=repository.repoid,
            commit_id=head_commit.commitid,
        )
    )

    assert res == {"merged_count": 2, "soft_deleted_count": 2}
    dbsession.refresh(first_commit)
    dbsession.refresh(second_commit)
    dbsession.refresh(third_commit)
    dbsession.refresh(fourth_commit)
    assert not first_commit.deleted
    assert second_commit.deleted
    assert not third_commit.deleted
    assert fourth_commit.deleted
    assert first_commit.merged
    assert not second_commit.merged
    assert third_commit.merged
    assert not fourth_commit.merged
    assert first_commit.branch == "lookatthis"
    assert third_commit.branch == "lookatthis"


def test_update_pull_commits_not_merged(
    dbsession, repository, base_commit, head_commit, pull
):
    pull.state = "open"
    pullid = pull.pullid
    base_commit.pullid = pullid
    head_commit.pullid = pullid
    first_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    second_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    third_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    fourth_commit = CommitFactory.create(
        repository=repository, pullid=pullid, merged=False
    )
    dbsession.add(pull)
    dbsession.add(first_commit)
    dbsession.add(second_commit)
    dbsession.add(third_commit)
    dbsession.add(fourth_commit)
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.flush()
    task = PullSyncTask()
    enriched_pull = EnrichedPull(
        database_pull=pull, provider_pull=dict(base=dict(branch="lookatthis"))
    )
    commits = [first_commit.commitid, third_commit.commitid]
    commits_at_base = {
        "commitid": first_commit.commitid,
        "parents": [{"commitid": third_commit.commitid, "parents": []}],
    }
    current_yaml = UserYaml.from_dict(dict())
    mock_repo_provider = MagicMock(
        get_commit=MagicMock(return_value=dict(parents=["1", "2"]))
    )
    res = task.update_pull_commits(
        mock_repo_provider,
        enriched_pull,
        commits,
        commits_at_base,
        current_yaml,
        repository,
    )
    assert res == {"merged_count": 0, "soft_deleted_count": 2}
    dbsession.refresh(first_commit)
    dbsession.refresh(second_commit)
    dbsession.refresh(third_commit)
    dbsession.refresh(fourth_commit)
    assert not first_commit.deleted
    assert second_commit.deleted
    assert not third_commit.deleted
    assert fourth_commit.deleted
    assert not first_commit.merged
    assert not second_commit.merged
    assert not third_commit.merged
    assert not fourth_commit.merged


def test_call_pullsync_task_no_head_commit(dbsession, mocker, mock_redis):
    task = PullSyncTask()
    pull = PullFactory.create(head="head_commit_nonexistent_sha", state="open")
    dbsession.add(pull)
    dbsession.flush()
    mocked_fetch_pr = mocker.patch(
        "tasks.sync_pull.fetch_and_update_pull_request_information"
    )
    mocked_fetch_pr.return_value = EnrichedPull(database_pull=pull, provider_pull={})
    res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": False,
        "pull_updated": False,
        "reason": "no_head",
    }


def test_call_pullsync_task_nolock(dbsession, mock_redis, pull):
    task = PullSyncTask()
    mock_redis.lock.return_value.__enter__.side_effect = LockError
    res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": False,
        "pull_updated": False,
        "reason": "unable_fetch_lock",
    }


def test_call_pullsync_task_no_database_pull(dbsession, mocker, mock_redis, repository):
    task = PullSyncTask()
    mocked_fetch_pr = mocker.patch(
        "tasks.sync_pull.fetch_and_update_pull_request_information"
    )
    mocked_fetch_pr.return_value = EnrichedPull(database_pull=None, provider_pull=None)
    res = task.run_impl(dbsession, repoid=repository.repoid, pullid=99)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": False,
        "pull_updated": False,
        "reason": "no_db_pull",
    }


def test_call_pullsync_task_no_provider_pull_only(
    dbsession, mocker, mock_redis, repository, pull
):
    task = PullSyncTask()
    mocked_fetch_pr = mocker.patch(
        "tasks.sync_pull.fetch_and_update_pull_request_information"
    )
    mocked_fetch_pr.return_value = EnrichedPull(database_pull=pull, provider_pull=None)
    res = task.run_impl(dbsession, repoid=repository.repoid, pullid=99)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": False,
        "pull_updated": False,
        "reason": "not_in_provider",
    }


def test_call_pullsync_no_bot(dbsession, mock_redis, mocker, pull):
    task = PullSyncTask()
    mocker.patch(
        "tasks.sync_pull.get_repo_provider_service",
        side_effect=RepositoryWithoutValidBotError(),
    )
    res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": False,
        "pull_updated": False,
        "reason": "no_bot",
    }


def test_call_pullsync_no_apps_available_rate_limit(
    dbsession, mock_redis, mocker, pull
):
    task = PullSyncTask()
    mocker.patch(
        "tasks.sync_pull.get_repo_provider_service",
        side_effect=NoConfiguredAppsAvailable(
            apps_count=1, rate_limited_count=1, suspended_count=0
        ),
    )
    with pytest.raises(Retry):
        task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)


def test_call_pullsync_no_apps_available_suspended(dbsession, mock_redis, mocker, pull):
    task = PullSyncTask()
    mocker.patch(
        "tasks.sync_pull.get_repo_provider_service",
        side_effect=NoConfiguredAppsAvailable(
            apps_count=1, rate_limited_count=0, suspended_count=1
        ),
    )
    res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": False,
        "pull_updated": False,
        "reason": "no_configured_apps_available",
    }


def test_call_pullsync_no_permissions_get_compare(
    dbsession,
    mock_redis,
    mocker,
    mock_repo_provider,
    mock_storage,
    repository,
    base_commit,
    head_commit,
    pull,
):
    mocker.patch.object(PullSyncTask, "app")
    task = PullSyncTask()
    mocked_fetch_pr = mocker.patch(
        "tasks.sync_pull.fetch_and_update_pull_request_information"
    )
    mocked_fetch_pr.return_value = EnrichedPull(
        database_pull=pull, provider_pull={"head"}
    )
    mock_repo_provider.get_compare.side_effect = TorngitClientError(
        403, "response", "message"
    )
    mock_repo_provider.get_pull_request_commits.side_effect = TorngitClientError(
        403, "response", "message"
    )
    res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": True,
        "pull_updated": True,
        "reason": "success",
    }


def test_run_impl_unobtainable_lock(dbsession, mock_redis, pull):
    mock_redis.lock.side_effect = LockError()
    mock_redis.exists.return_value = True
    task = PullSyncTask()
    task.request.retries = 0
    res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
    assert res == {
        "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
        "notifier_called": False,
        "pull_updated": False,
        "reason": "unable_fetch_lock",
    }


def test_was_pr_merged_with_squash():
    ancestors_tree = {
        "commitid": "c739768fcac68144a3a6d82305b9c4106934d31a",
        "parents": [
            {
                "commitid": "b33e12816cc3f386dae8add4968cedeff5155021",
                "parents": [
                    {
                        "commitid": "743b04806ea677403aa2ff26c6bdeb85005de658",
                        "parents": [],
                    },
                    {
                        "commitid": "some_commit",
                        "parents": [{"commitid": "paaaaaaaaaaa", "parents": []}],
                    },
                ],
            }
        ],
    }
    task = PullSyncTask()
    assert not task.was_squash_via_ancestor_tree(
        ["c739768fcac68144a3a6d82305b9c4106934d31a"], ancestors_tree
    )
    assert task.was_squash_via_ancestor_tree(["some_other_stuff"], ancestors_tree)
    assert not task.was_squash_via_ancestor_tree(
        ["some_other_stuff", "some_commit"], ancestors_tree
    )


def test_cache_changes_stores_changed_files_in_redis_if_owner_is_whitelisted(
    dbsession,
    mock_redis,
    mock_repo_provider,
    mocker,
    repository,
    base_commit,
    head_commit,
    pull,
):
    os.environ["OWNERS_WITH_CACHED_CHANGES"] = f"{pull.repository.owner.ownerid}"

    changes = [Change(path="f.py")]
    mocker.patch(
        "tasks.sync_pull.get_changes",
        lambda base_report, head_report, diff: changes,
    )

    task = PullSyncTask()
    task.cache_changes(pull, changes)

    mock_redis.set.assert_called_once_with(
        "/".join(
            (
                "compare-changed-files",
                pull.repository.owner.service,
                pull.repository.owner.username,
                pull.repository.name,
                f"{pull.pullid}",
            )
        ),
        json.dumps(["f.py"]),
        ex=86400,
    )


def test_trigger_ai_pr_review(
    dbsession, mocker, repository, base_commit, head_commit, pull
):
    pullid = pull.pullid
    base_commit.pullid = pullid
    head_commit.pullid = pullid
    dbsession.add(pull)
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.flush()
    task = PullSyncTask()
    apply_async = mocker.patch.object(
        task.app.tasks["app.tasks.ai_pr_review.AiPrReview"], "apply_async"
    )
    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull=dict(base=dict(branch="lookatthis"), labels=["ai-pr-review"]),
    )
    current_yaml = UserYaml.from_dict(
        {
            "ai_pr_review": {
                "enabled": True,
                "method": "label",
                "label_name": "ai-pr-review",
            }
        }
    )
    task.trigger_ai_pr_review(enriched_pull, current_yaml)
    apply_async.assert_called_once_with(
        kwargs=dict(repoid=pull.repoid, pullid=pull.pullid)
    )

    apply_async.reset_mock()
    current_yaml = UserYaml.from_dict(
        {
            "ai_pr_review": {
                "enabled": True,
            }
        }
    )
    task.trigger_ai_pr_review(enriched_pull, current_yaml)
    apply_async.assert_called_once_with(
        kwargs=dict(repoid=pull.repoid, pullid=pull.pullid)
    )

    apply_async.reset_mock()
    current_yaml = UserYaml.from_dict(
        {
            "ai_pr_review": {
                "enabled": True,
                "method": "auto",
            }
        }
    )
    task.trigger_ai_pr_review(enriched_pull, current_yaml)
    apply_async.assert_called_once_with(
        kwargs=dict(repoid=pull.repoid, pullid=pull.pullid)
    )

    apply_async.reset_mock()
    current_yaml = UserYaml.from_dict(
        {
            "ai_pr_review": {
                "enabled": True,
                "method": "label",
                "label_name": "other",
            }
        }
    )
    task.trigger_ai_pr_review(enriched_pull, current_yaml)
    assert not apply_async.called


@pytest.mark.parametrize("flake_detection", [False, True])
@pytest.mark.django_db
def test_trigger_process_flakes(dbsession, mocker, flake_detection, repository):
    mock_all_plans_and_tiers()

    current_yaml = UserYaml.from_dict(
        {
            "test_analytics": {
                "flake_detection": flake_detection,
            }
        }
    )

    commit = CommitFactory.create(repository=repository)
    dbsession.add(commit)
    dbsession.flush()

    task = PullSyncTask()
    apply_async: MagicMock = mocker.patch.object(
        task.app.tasks["app.tasks.flakes.ProcessFlakesTask"], "apply_async"
    )

    if flake_detection:
        TestFactory.create(repository=repository)
        dbsession.flush()

    task.trigger_process_flakes(
        dbsession,
        repository,
        commit.commitid,
        current_yaml,
    )
    if flake_detection:
        apply_async.assert_called_once_with(
            kwargs=dict(
                repo_id=repository.repoid,
                commit_id=commit.commitid,
            )
        )
    else:
        apply_async.assert_not_called()
