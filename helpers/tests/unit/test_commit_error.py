import logging

import pytest

from database.tests.factories import CommitFactory
from helpers.save_commit_error import save_repo_bot_error, save_yaml_error

LOGGER = logging.getLogger(__name__)


class TestSaveCommitError(object):
    @pytest.mark.asyncio
    async def test_save_bot_error(self, mocker, dbsession):
        commit = CommitFactory.create()

        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        commit.get_db_session = mocked_get_db_session

        save_repo_bot_error(commit)

        assert commit.errors
        assert len(commit.errors) == 1

    @pytest.mark.asyncio
    async def test_save_bot_error_already_saved(self, mocker, dbsession):
        commit = CommitFactory.create()

        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        commit.get_db_session = mocked_get_db_session

        save_repo_bot_error(commit)
        save_repo_bot_error(commit)

        assert len(commit.errors) == 1

    @pytest.mark.asyncio
    async def test_save_bot_error_exception(self, mocker, caplog):
        commit = CommitFactory.create()

        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = None
        commit.get_db_session = mocked_get_db_session

        save_repo_bot_error(commit)
        assert "Error saving bot commit error -repo bot invalid-\n" in caplog.text

    @pytest.mark.asyncio
    async def test_save_yaml_error(self, mocker, dbsession):
        commit = CommitFactory.create()

        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        commit.get_db_session = mocked_get_db_session

        save_yaml_error(commit, "invalid_yaml")
        save_yaml_error(commit, "repo_bot_invalid")

        assert commit.errors
        assert len(commit.errors) == 2

    @pytest.mark.asyncio
    async def test_save_yaml_error_already_saved(self, mocker, dbsession):
        commit = CommitFactory.create()

        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        commit.get_db_session = mocked_get_db_session

        save_yaml_error(commit, "invalid_yaml")
        save_yaml_error(commit, "invalid_yaml")
        save_yaml_error(commit, "repo_bot_invalid")

        assert len(commit.errors) == 2

    @pytest.mark.asyncio
    async def test_save_yaml_error_exception(self, mocker, caplog):
        commit = CommitFactory.create()

        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = None
        commit.get_db_session = mocked_get_db_session

        save_yaml_error(commit, "invalid_yaml")
        assert "Error saving yaml commit error" in caplog.text
