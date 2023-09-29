import logging
from smtplib import (
    SMTPDataError,
    SMTPNotSupportedError,
    SMTPRecipientsRefused,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)
from unittest.mock import MagicMock, call, patch

import pytest

import services.smtp
from helpers.email import Email
from services.smtp import SMTPService, SMTPServiceError

LOGGER = logging.getLogger(__name__)

to_addr = "test_to@codecov.io"
from_addr = "test_from@codecov.io"
test_email = Email(
    from_addr=from_addr,
    subject="Test subject",
    text="Hello world",
    to_addr=to_addr,
)


class TestSMTP(object):
    def test_correct_init(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        mock_configuration._params["services"]["smtp"]["username"] = "test_username"
        mock_configuration._params["services"]["smtp"]["password"] = "test_password"
        m = mocker.patch("ssl.create_default_context", return_value=MagicMock())
        service = SMTPService()
        service.connection.starttls.assert_called_with(context=m.return_value)
        service.connection.login.assert_called_with("test_username", "test_password")

    def test_idempotentconnectionection(self, mocker, mock_configuration):
        first = SMTPService()
        firstconnection = first.connection
        second = SMTPService()
        secondconnection = second.connection
        assert id(firstconnection) == id(secondconnection)

    def test_empty_config(self, mocker, mock_configuration):
        SMTPService.connection = None
        del mock_configuration._params["services"]["smtp"]
        service = SMTPService()
        assert service.connection is None

    def test_send(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        email = Email(
            to_addr="test_to@codecov.io",
            from_addr="test_from@codecov.io",
            subject="Test subject",
            text="test text",
            html="test html",
        )

        smtp = SMTPService()
        smtp.send(email=email)

        smtp.connection.send_message.assert_called_with(email.message)

    def test_send_email_recipients_refused(self, mocker, mock_configuration, dbsession):
        SMTPService.connection = None
        m = MagicMock()
        m.configure_mock(**{"send_message.side_effect": SMTPRecipientsRefused(to_addr)})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        with pytest.raises(SMTPServiceError, match="All recipients were refused"):
            smtp.send(email=test_email)

    def test_send_email_sender_refused(self, mocker, mock_configuration, dbsession):
        SMTPService.connection = None
        m = MagicMock()
        m.configure_mock(
            **{"send_message.side_effect": SMTPSenderRefused(123, "", to_addr)}
        )
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        with pytest.raises(SMTPServiceError, match="Sender was refused"):
            smtp.send(email=test_email)

    def test_send_email_data_error(self, mocker, mock_configuration, dbsession):
        SMTPService.connection = None
        m = MagicMock()
        m.configure_mock(**{"send_message.side_effect": SMTPDataError(123, "")})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        with pytest.raises(
            SMTPServiceError, match="The SMTP server did not accept the data"
        ):
            smtp.send(email=test_email)

    def test_send_email_sends_errs(self, mocker, mock_configuration, dbsession):
        SMTPService.connection = None
        m = MagicMock()
        m.configure_mock(**{"send_message.return_value": [(123, "abc"), (456, "def")]})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        with pytest.raises(SMTPServiceError, match="123 abc 456 def"):
            smtp.send(email=test_email)

    def test_smtp_active(self, mocker, mock_configuration, dbsession):
        smtp = SMTPService()
        assert smtp.active() == True
        SMTPService.connection = None
        assert smtp.active() == False

    def test_smtp_disconnected(self, mocker, mock_configuration, dbsession):
        mock_configuration._params["services"]["smtp"]["username"] = "test_username"
        mock_configuration._params["services"]["smtp"]["password"] = "test_password"

        m = MagicMock()
        m.configure_mock(**{"noop.side_effect": SMTPServerDisconnected()})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )
        email = Email(
            to_addr="test_to@codecov.io",
            from_addr="test_from@codecov.io",
            subject="Test subject",
            text="test text",
            html="test html",
        )

        smtp = SMTPService()

        smtp.send(email)

        smtp.connection.connect.assert_has_calls([call("testserver", 12345)])
        smtp.connection.starttls.assert_has_calls(
            [call(context=smtp.ssl_context), call(context=smtp.ssl_context)]
        )
        smtp.connection.login.assert_has_calls(
            [
                call("test_username", "test_password"),
                call("test_username", "test_password"),
            ]
        )
        smtp.connection.noop.assert_has_calls([call()])
        smtp.connection.send_message(call(email.message))

    def test_smtp_tls_not_supported(
        self, caplog, mocker, mock_configuration, dbsession
    ):
        services.smtp.SMTPService.connection = None
        m = MagicMock()
        m.configure_mock(**{"starttls.side_effect": SMTPNotSupportedError()})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        with caplog.at_level(logging.WARNING):
            smtp = SMTPService()

        assert (
            "Server does not support TLS, continuing initialization of SMTP connection"
            in caplog.text
        )

    def test_smtp_auth_not_supported(
        self, caplog, mocker, mock_configuration, dbsession
    ):
        services.smtp.SMTPService.connection = None

        mock_configuration._params["services"]["smtp"]["username"] = "test_username"
        mock_configuration._params["services"]["smtp"]["password"] = "test_password"

        m = MagicMock()
        m.configure_mock(**{"login.side_effect": SMTPNotSupportedError()})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        with caplog.at_level(logging.WARNING):
            smtp = SMTPService()

        assert (
            "Server does not support AUTH, continuing initialization of SMTP connection"
            in caplog.text
        )
