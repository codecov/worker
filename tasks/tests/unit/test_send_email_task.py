import json
from pathlib import Path
from smtplib import SMTPDataError, SMTPRecipientsRefused, SMTPSenderRefused
from unittest.mock import MagicMock

import pytest
from jinja2 import TemplateNotFound, UndefinedError
from shared.config import ConfigHelper
from shared.utils.test_utils.mock_metrics import mock_metrics as utils_mock_metrics

import services.smtp
from database.tests.factories import OwnerFactory
from tasks.send_email import SendEmailTask

here = Path(__file__)

to_addr = "test_to@codecov.io"


@pytest.fixture
def mock_configuration_no_smtp(mocker):
    m = mocker.patch("shared.config._get_config_instance")
    mock_config = ConfigHelper()
    m.return_value = mock_config
    our_config = {
        "bitbucket": {"bot": {"username": "codecov-io"}},
        "services": {
            "minio": {
                "access_key_id": "codecov-default-key",
                "bucket": "archive",
                "hash_key": "88f572f4726e4971827415efa8867978",
                "periodic_callback_ms": False,
                "secret_access_key": "codecov-default-secret",
                "verify_ssl": False,
            },
            "redis_url": "redis://redis:@localhost:6379/",
        },
        "setup": {
            "codecov_url": "https://codecov.io",
            "encryption_secret": "zp^P9*i8aR3",
            "telemetry": {
                "endpoint_override": "abcde",
            },
        },
    }
    mock_config.set_params(our_config)
    return mock_config


class TestSendEmailTask(object):
    @pytest.mark.asyncio
    async def test_send_email(
        self,
        mocker,
        mock_configuration,
        dbsession,
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
            subject="Test",
            username="test_username",
        )

        assert metrics.data["worker.tasks.send_email.attempt"] == 1
        assert metrics.data["worker.tasks.send_email.succeed"] == 1
        assert metrics.data["worker.tasks.send_email.fail"] == 0

    @pytest.mark.asyncio
    async def test_send_email_non_existent_template(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        with pytest.raises(TemplateNotFound):
            result = await SendEmailTask().run_async(
                db_session=dbsession,
                ownerid=owner.ownerid,
                from_addr="test_from@codecov.io",
                template_name="non_existent",
                subject="Test",
                username="test_username",
            )

    @pytest.mark.asyncio
    async def test_send_email_missing_kwargs(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        with pytest.raises(UndefinedError):
            result = await SendEmailTask().run_async(
                db_session=dbsession,
                ownerid=owner.ownerid,
                from_addr="test_from@codecov.io",
                subject="Test",
                template_name="test",
            )

    @pytest.mark.asyncio
    async def test_send_email_invalid_owner_no_list_type(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=99999999,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_send_email_recipients_refused(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(**{"send.side_effect": SMTPRecipientsRefused(to_addr)})
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result["email_successful"] == False
        assert result["err_msg"] == "All recipients were refused"

    @pytest.mark.asyncio
    async def test_send_email_sender_refused(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(
            **{"send.side_effect": SMTPSenderRefused(123, "", to_addr)}
        )
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result["email_successful"] == False
        assert result["err_msg"] == "Sender was refused"

    @pytest.mark.asyncio
    async def test_send_email_data_error(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(**{"send.side_effect": SMTPDataError(123, "")})
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result["email_successful"] == False
        assert result["err_msg"] == "The SMTP server did not accept the data"

    @pytest.mark.asyncio
    async def test_send_email_sends_errs(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(**{"send.return_value": [(123, "abc"), (456, "def")]})
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result["email_successful"] == False
        assert result["err_msg"] == "123 abc 456 def"

    @pytest.mark.asyncio
    async def test_send_email_no_smtp_config(
        self, mocker, mock_configuration_no_smtp, dbsession
    ):
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = await SendEmailTask().run_async(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result is None
        services.smtp._smtp_service = None  # reset SMTP service
