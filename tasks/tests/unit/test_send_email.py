import json
from pathlib import Path

import pytest
from jinja2 import TemplateNotFound, UndefinedError
from shared.utils.test_utils.mock_metrics import mock_metrics as utils_mock_metrics

from database.tests.factories import OwnerFactory
from tasks.send_email import SendEmailTask

here = Path(__file__)

to_addr = "test_to@codecov.io"


class TestSendEmailTask(object):
    @pytest.mark.asyncio
    async def test_send_email(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_smtp,
        mock_redis,
    ):
        metrics = utils_mock_metrics(mocker)
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            username="test_username",
        )

        assert metrics.data["worker.tasks.send_email.attempt"] == 1
        assert metrics.data["worker.tasks.send_email.succeed"] == 1
        assert metrics.data["worker.tasks.send_email.fail"] == 0

    @pytest.mark.asyncio
    async def test_send_email_non_existent_template(
        self, mocker, mock_configuration, dbsession, codecov_vcr, mock_smtp
    ):
        to_addr = "test_to@codecov.io"
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        with pytest.raises(TemplateNotFound):
            result = await SendEmailTask().run_async(
                db_session=dbsession,
                ownerid=owner.ownerid,
                from_addr="test_from@codecov.io",
                template_name="non_existent",
                username="test_username",
            )

    @pytest.mark.asyncio
    async def test_send_email_missing_kwargs(
        self, mocker, mock_configuration, dbsession, codecov_vcr, mock_smtp
    ):
        to_addr = "test_to@codecov.io"
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        with pytest.raises(UndefinedError):
            result = await SendEmailTask().run_async(
                db_session=dbsession,
                ownerid=owner.ownerid,
                from_addr="test_from@codecov.io",
                template_name="test",
            )

    @pytest.mark.asyncio
    async def test_send_email_invalid_owner_no_list_type(
        self, mocker, mock_configuration, dbsession, codecov_vcr, mock_smtp
    ):
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=99999999,
            from_addr="test_from@codecov.io",
            template_name="test",
            username="test_username",
        )
