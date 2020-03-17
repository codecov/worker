from pathlib import Path

from sqlalchemy.exc import DBAPIError
import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded


from tasks.base import BaseCodecovTask

here = Path(__file__)


class SampleTask(BaseCodecovTask):
    async def run_async(self, dbsession):
        return {"unusual": "return", "value": ["There"]}

    def write_to_db(self):
        return False


class SampleTaskWithError(BaseCodecovTask):
    async def run_async(self, dbsession):
        raise DBAPIError("statement", "params", "orig")

    def write_to_db(self):
        return False

    def retry(self):
        # Fake retry method
        raise Retry()


class SampleTaskWithSoftTimeout(BaseCodecovTask):
    async def run_async(self, dbsession):
        raise SoftTimeLimitExceeded()


class TestBaseTask(object):
    def test_sample_run(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        result = SampleTask().run()
        assert result == {"unusual": "return", "value": ["There"]}

    def test_sample_run_db_exception(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(Retry):
            SampleTaskWithError().run()

    def test_sample_run_softimeout(self, mocker, dbsession):
        mocked_get_db_session = mocker.patch("tasks.base.get_db_session")
        mocked_get_db_session.return_value = dbsession
        with pytest.raises(SoftTimeLimitExceeded):
            SampleTaskWithSoftTimeout().run()
