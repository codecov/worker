from pathlib import Path

import pytest
from jinja2 import TemplateNotFound, UndefinedError
from shared.config import ConfigHelper

from database.tests.factories import OwnerFactory
from services.smtp import SMTPService, SMTPServiceError
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
    def test_send_email(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_storage,
        mock_smtp,
        mock_redis,
    ):
        mock_smtp.configure_mock(**{"send.return_value": None})
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )

        assert result == {"email_successful": True, "err_msg": None}

    def test_send_email_non_existent_template(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        with pytest.raises(TemplateNotFound):
            result = SendEmailTask().run_impl(
                db_session=dbsession,
                ownerid=owner.ownerid,
                from_addr="test_from@codecov.io",
                template_name="non_existent",
                subject="Test",
                username="test_username",
            )

    def test_send_email_no_owner(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        owner = OwnerFactory.create(email=None)
        dbsession.add(owner)
        dbsession.flush()
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )

        assert result == {
            "email_successful": False,
            "err_msg": "Owner does not have email",
        }

    def test_send_email_missing_kwargs(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        with pytest.raises(UndefinedError):
            result = SendEmailTask().run_impl(
                db_session=dbsession,
                ownerid=owner.ownerid,
                from_addr="test_from@codecov.io",
                subject="Test",
                template_name="test",
            )

    def test_send_email_invalid_owner_no_list_type(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=99999999,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result == {"email_successful": False, "err_msg": "Unable to find owner"}

    def test_send_email_recipients_refused(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(
            **{"send.side_effect": SMTPServiceError("All recipients were refused")}
        )

        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )

        assert result["email_successful"] == False
        assert result["err_msg"] == "All recipients were refused"

    def test_send_email_sender_refused(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(
            **{"send.side_effect": SMTPServiceError("Sender was refused")}
        )
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result["email_successful"] == False
        assert result["err_msg"] == "Sender was refused"

    def test_send_email_data_error(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(
            **{
                "send.side_effect": SMTPServiceError(
                    "The SMTP server did not accept the data"
                )
            }
        )
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result["email_successful"] == False
        assert result["err_msg"] == "The SMTP server did not accept the data"

    def test_send_email_sends_errs(
        self, mocker, mock_configuration, dbsession, mock_smtp
    ):
        mock_smtp.configure_mock(
            **{"send.side_effect": SMTPServiceError("123 abc 456 def")}
        )
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result["email_successful"] == False
        assert result["err_msg"] == "123 abc 456 def"

    def test_send_email_no_smtp_config(
        self, mocker, mock_configuration_no_smtp, dbsession
    ):
        SMTPService.connection = None
        owner = OwnerFactory.create(email=to_addr)
        dbsession.add(owner)
        dbsession.flush()
        result = SendEmailTask().run_impl(
            db_session=dbsession,
            ownerid=owner.ownerid,
            from_addr="test_from@codecov.io",
            template_name="test",
            subject="Test",
            username="test_username",
        )
        assert result == {
            "email_successful": False,
            "err_msg": "Cannot send email because SMTP is not configured for this installation of codecov",
        }
