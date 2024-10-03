import json
import os
from pathlib import Path

import pytest
from celery.exceptions import Retry
from mock.mock import MagicMock
from redis.exceptions import LockError
from shared.reports.types import Change
from shared.torngit.exceptions import TorngitClientError

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from database.tests.factories.reports import TestFactory
from helpers.exceptions import NoConfiguredAppsAvailable, RepositoryWithoutValidBotError
from services.repository import EnrichedPull
from services.yaml import UserYaml
from tasks.sync_pull import PullSyncTask

here = Path(__file__)


class TestPullSyncTask(object):
    @pytest.mark.parametrize(
        "flake_detection_config, flake_detection,flaky_shadow_mode,tests_exist,outcome",
        [
            (False, True, True, True, False),
            (True, False, False, False, False),
            (True, False, False, True, False),
            (True, True, False, True, True),
            (True, False, True, True, True),
            (True, True, True, True, True),
        ],
    )
    def test_update_pull_commits_merged(
        self,
        dbsession,
        mocker,
        flake_detection_config,
        flake_detection,
        flaky_shadow_mode,
        tests_exist,
        outcome,
    ):
        if flake_detection:
            mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
            mock_feature.check_value.return_value = True

        if flaky_shadow_mode:
            _flaky_shadow_mode_feature = mocker.patch(
                "services.test_results.FLAKY_SHADOW_MODE"
            )
            _flaky_shadow_mode_feature.check_value.return_value = True

        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()

        if tests_exist:
            t = TestFactory(repository=repository)
            dbsession.add(t)
            dbsession.flush()

        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository)
        pull = PullFactory.create(
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
            state="merged",
        )
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
            provider_pull=dict(
                base=dict(branch="lookatthis"), head=dict(branch="thing")
            ),
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
                    "flake_detection": flake_detection_config,
                }
            }
        )
        mock_repo_provider = MagicMock(
            get_commit=MagicMock(return_value=dict(parents=["1", "2"]))
        )
        res = task.update_pull_commits(
            mock_repo_provider, enriched_pull, commits, commits_at_base, current_yaml
        )

        if outcome:
            apply_async.assert_called_once_with(
                kwargs=dict(
                    repo_id=repository.repoid,
                    commit_id_list=[head_commit.commitid],
                    branch="thing",
                )
            )
        else:
            apply_async.assert_not_called()

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

    def test_update_pull_commits_not_merged(self, dbsession, mocker):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository)
        pull = PullFactory.create(
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
            state="open",
        )
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
            mock_repo_provider, enriched_pull, commits, commits_at_base, current_yaml
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

    def test_call_pullsync_task_no_head_commit(self, dbsession, mocker, mock_redis):
        task = PullSyncTask()
        pull = PullFactory.create(head="head_commit_nonexistent_sha", state="open")
        dbsession.add(pull)
        dbsession.flush()
        mocked_fetch_pr = mocker.patch(
            "tasks.sync_pull.fetch_and_update_pull_request_information"
        )
        mocked_fetch_pr.return_value = EnrichedPull(
            database_pull=pull, provider_pull={}
        )
        res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "no_head",
        }

    def test_call_pullsync_task_nolock(self, dbsession, mock_redis):
        task = PullSyncTask()
        pull = PullFactory.create(state="open")
        dbsession.add(pull)
        dbsession.flush()
        mock_redis.lock.return_value.__enter__.side_effect = LockError
        res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "unable_fetch_lock",
        }

    def test_call_pullsync_task_no_database_pull(self, dbsession, mocker, mock_redis):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        task = PullSyncTask()
        mocked_fetch_pr = mocker.patch(
            "tasks.sync_pull.fetch_and_update_pull_request_information"
        )
        mocked_fetch_pr.return_value = EnrichedPull(
            database_pull=None, provider_pull=None
        )
        res = task.run_impl(dbsession, repoid=repository.repoid, pullid=99)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "no_db_pull",
        }

    def test_call_pullsync_task_no_provider_pull_only(
        self, dbsession, mocker, mock_redis
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        pull = PullFactory.create(state="open", repository=repository)
        dbsession.add(pull)
        dbsession.flush()
        task = PullSyncTask()
        mocked_fetch_pr = mocker.patch(
            "tasks.sync_pull.fetch_and_update_pull_request_information"
        )
        mocked_fetch_pr.return_value = EnrichedPull(
            database_pull=pull, provider_pull=None
        )
        res = task.run_impl(dbsession, repoid=repository.repoid, pullid=99)
        assert res == {
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "notifier_called": False,
            "pull_updated": False,
            "reason": "not_in_provider",
        }

    def test_call_pullsync_no_bot(self, dbsession, mock_redis, mocker):
        task = PullSyncTask()
        pull = PullFactory.create(state="open")
        dbsession.add(pull)
        dbsession.flush()
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
        self, dbsession, mock_redis, mocker
    ):
        task = PullSyncTask()
        pull = PullFactory.create(state="open")
        dbsession.add(pull)
        dbsession.flush()
        mocker.patch(
            "tasks.sync_pull.get_repo_provider_service",
            side_effect=NoConfiguredAppsAvailable(
                apps_count=1, rate_limited_count=1, suspended_count=0
            ),
        )
        with pytest.raises(Retry):
            task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)

    def test_call_pullsync_no_apps_available_suspended(
        self, dbsession, mock_redis, mocker
    ):
        task = PullSyncTask()
        pull = PullFactory.create(state="open")
        dbsession.add(pull)
        dbsession.flush()
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
        self, dbsession, mock_redis, mocker, mock_repo_provider, mock_storage
    ):
        mocker.patch.object(PullSyncTask, "app")
        task = PullSyncTask()
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository)
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        pull = PullFactory.create(
            state="open",
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
        )
        dbsession.add(pull)
        dbsession.flush()
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

    def test_run_impl_unobtainable_lock(self, dbsession, mocker, mock_redis):
        pull = PullFactory.create()
        dbsession.add(pull)
        dbsession.flush()
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

    def test_was_pr_merged_with_squash(self):
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
        self, dbsession, mock_redis, mock_repo_provider, mocker
    ):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository)
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        pull = PullFactory.create(
            state="open",
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
        )

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

    def test_trigger_ai_pr_review(self, dbsession, mocker):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository)
        pull = PullFactory.create(
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
        )
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

    @pytest.mark.parametrize(
        "flake_detection", [None, "FLAKY_TEST_DETECTION", "FLAKY_SHADOW_MODE"]
    )
    def test_trigger_process_flakes(self, dbsession, mocker, flake_detection):
        current_yaml = UserYaml.from_dict(dict())
        if flake_detection:
            mock_feature = mocker.patch(f"services.test_results.{flake_detection}")
            mock_feature.check_value.return_value = True

            if flake_detection == "FLAKY_TEST_DETECTION":
                current_yaml = UserYaml.from_dict(
                    {
                        "test_analytics": {
                            "flake_detection": flake_detection,
                        }
                    }
                )

        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        commit = CommitFactory.create(repository=repository)
        dbsession.add(commit)
        dbsession.flush()

        dbsession.flush()
        task = PullSyncTask()

        apply_async: MagicMock = mocker.patch.object(
            task.app.tasks["app.tasks.flakes.ProcessFlakesTask"], "apply_async"
        )

        task.trigger_process_flakes(
            repository.repoid,
            commit.commitid,
            "main",
            current_yaml,
        )
        if flake_detection:
            apply_async.assert_called_once_with(
                kwargs=dict(
                    repo_id=repository.repoid,
                    commit_id_list=[commit.commitid],
                    branch="main",
                )
            )
        else:
            apply_async.assert_not_called()
