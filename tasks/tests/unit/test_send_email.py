import json
import pytest
from pathlib import Path

from database.tests.factories import OwnerFactory
from tasks.send_email import SendEmailTask

here = Path(__file__)


class TestSendEmailTask(object):
    @pytest.mark.asyncio
    async def test_end_of_trial_email_with_list_type(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        owner = OwnerFactory.create(ownerid=1, email="felipe@codecov.io")
        dbsession.add(owner)
        result = await SendEmailTask().run_async(
            db_session=dbsession, ownerid=owner.ownerid, list_type="end-of-trial"
        )
        assert result["job_id"] == "9791f6a7-3d3b-4ae9-8f71-67bd98f33008"

    async def test_end_of_trial_email_with_email_type(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
    ):
        owner = OwnerFactory.create(ownerid=1, email="felipe@codecov.io")
        dbsession.add(owner)
        result = await SendEmailTask().run_async(
            db_session=dbsession, ownerid=owner.ownerid, email_type="end-of-trial"
        )
        assert result["job_id"] == "9791f6a7-3d3b-4ae9-8f71-67bd98f33008"

    @pytest.mark.asyncio
    async def test_send_email_invalid_owner(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        result = await SendEmailTask().run_async(
            db_session=dbsession, ownerid=999999999, list_type="end-of-trial"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_send_email_invalid_list_with_list_type(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        owner = OwnerFactory.create(ownerid=1, email="felipe@codecov.io")
        dbsession.add(owner)
        result = await SendEmailTask().run_async(
            db_session=dbsession, ownerid=owner.ownerid, list_type="fake-list"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_send_email_invalid_list_with_email_type(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        owner = OwnerFactory.create(ownerid=1, email="felipe@codecov.io")
        dbsession.add(owner)
        result = await SendEmailTask().run_async(
            db_session=dbsession, ownerid=owner.ownerid, email_type="fake-list"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_send_email_no_list(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        owner = OwnerFactory.create(ownerid=1, email="felipe@codecov.io")
        dbsession.add(owner)
        result = await SendEmailTask().run_async(
            db_session=dbsession, ownerid=owner.ownerid
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_send_email_invalid_owner_no_list_type(
        self, mocker, mock_configuration, dbsession, codecov_vcr
    ):
        result = await SendEmailTask().run_async(
            db_session=dbsession, ownerid=999999999
        )
        assert result is None
