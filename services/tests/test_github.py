from unittest.mock import MagicMock

import pytest
from redis import RedisError

from database.models.core import GithubAppInstallation, Owner
from database.tests.factories.core import CommitFactory, RepositoryFactory
from services.github import get_github_app_for_commit, set_github_app_for_commit


class TestGetSetGithubAppsToCommits(object):
    def _get_commit(self, dbsession):
        commit = CommitFactory(repository__owner__service="github")
        dbsession.add(commit)
        dbsession.flush()
        return commit

    def _get_app(self, owner: Owner, dbsession):
        app = GithubAppInstallation(
            owner=owner, installation_id=1250, app_id=250, pem_path="some_path"
        )
        dbsession.add(app)
        dbsession.flush()
        return app

    @pytest.fixture
    def mock_redis(self, mocker):
        fake_redis = MagicMock(name="fake_redis")
        mock_conn = mocker.patch("services.github.get_redis_connection")
        mock_conn.return_value = fake_redis
        return fake_redis

    def test_set_app_for_commit_no_app(self, mock_redis, dbsession):
        commit = self._get_commit(dbsession)
        assert set_github_app_for_commit(None, commit) == False
        mock_redis.set.assert_not_called()

    def test_set_app_for_commit_redis_success(self, mock_redis, dbsession):
        commit = self._get_commit(dbsession)
        app = self._get_app(commit.repository.owner, dbsession)
        assert set_github_app_for_commit(app.id, commit) == True
        mock_redis.set.assert_called_with(
            f"app_to_use_for_commit_{commit.id}", str(app.id), ex=(60 * 60 * 2)
        )

    def test_set_app_for_commit_redis_error(self, mock_redis, dbsession):
        commit = self._get_commit(dbsession)
        mock_redis.set.side_effect = RedisError
        assert set_github_app_for_commit("1000", commit) == False
        mock_redis.set.assert_called_with(
            f"app_to_use_for_commit_{commit.id}", "1000", ex=(60 * 60 * 2)
        )

    def test_get_app_for_commit(self, mock_redis, dbsession):
        repo_github = RepositoryFactory(owner__service="github")
        repo_ghe = RepositoryFactory(owner__service="github_enterprise")
        repo_gitlab = RepositoryFactory(owner__service="gitlab")
        redis_keys = {
            "app_to_use_for_commit_12": b"1200",
            "app_to_use_for_commit_10": b"1000",
        }
        fake_commit_12 = MagicMock(
            name="fake_commit", **{"id": 12, "repository": repo_github}
        )
        fake_commit_10 = MagicMock(
            name="fake_commit",
            **{"id": 10, "repository": repo_ghe},
        )
        fake_commit_50 = MagicMock(
            name="fake_commit", **{"id": 50, "repository": repo_github}
        )
        fake_commit_gitlab = MagicMock(
            name="fake_commit", **{"id": 12, "repository": repo_gitlab}
        )
        mock_redis.get.side_effect = lambda key: redis_keys.get(key)
        assert get_github_app_for_commit(fake_commit_12) == "1200"
        assert get_github_app_for_commit(fake_commit_10) == "1000"
        assert get_github_app_for_commit(fake_commit_50) is None
        # This feature is Github-exclusive, so we skip checking for commits that are in repos of other providers
        assert get_github_app_for_commit(fake_commit_gitlab) is None

    def test_get_app_for_commit_error(self, mock_redis):
        repo_github = RepositoryFactory(owner__service="github")
        mock_redis.get.side_effect = RedisError
        fake_commit_12 = MagicMock(
            name="fake_commit", **{"id": 12, "repository": repo_github}
        )
        assert get_github_app_for_commit(fake_commit_12) is None
        mock_redis.get.assert_called_with("app_to_use_for_commit_12")

    @pytest.mark.integration
    def test_get_and_set_app_for_commit(self, dbsession):
        commit = self._get_commit(dbsession)
        # String
        set_github_app_for_commit("12", commit)
        assert get_github_app_for_commit(commit) == "12"
        # Int
        set_github_app_for_commit(24, commit)
        assert get_github_app_for_commit(commit) == "24"
