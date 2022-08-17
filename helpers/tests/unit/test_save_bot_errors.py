import pytest

from database.tests.factories import CommitFactory
from helpers.save_bot_error import save_bot_error


class TestSaveBotError(object):
    @pytest.mark.asyncio
    async def test_save_yaml_error(self, mocker, dbsession):
        commit = CommitFactory.create(
            repository__yaml={
                "coverage": {
                    "precision": 2,
                    "round": "down",
                    "range": [70.0, 100.0],
                    "status": {"project": True, "patch": True, "changes": False},
                }
            }
        )
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        commit.get_db_session = mocked_get_db_session

        save_bot_error(commit)

        assert commit.errors
        assert len(commit.errors) == 1
