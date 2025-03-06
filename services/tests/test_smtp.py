import logging
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPDataError,
    SMTPNotSupportedError,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)
from unittest.mock import MagicMock, call

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


@pytest.fixture
def set_username_and_password(mock_configuration):
    mock_configuration._params["services"]["smtp"]["username"] = "test_username"
    mock_configuration._params["services"]["smtp"]["password"] = "test_password"


@pytest.fixture
def reset_connection_at_start():
    services.smtp.SMTPService.connection = None


class TestSMTP(object):
    def test_correct_init(
        self,
        mocker,
        mock_configuration,
        set_username_and_password,
        reset_connection_at_start,
    ):
        mocker.patch("smtplib.SMTP")

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

    def test_empty_config(self, mocker, mock_configuration, reset_connection_at_start):
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

    def test_send_email_recipients_refused(
        self, mocker, mock_configuration, dbsession, reset_connection_at_start
    ):
        m = MagicMock()
        m.configure_mock(**{"send_message.side_effect": SMTPRecipientsRefused(to_addr)})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        with pytest.raises(SMTPServiceError, match="All recipients were refused"):
            smtp.send(email=test_email)

    def test_send_email_sender_refused(
        self, mocker, mock_configuration, dbsession, reset_connection_at_start
    ):
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

    def test_send_email_data_error(
        self, mocker, mock_configuration, dbsession, reset_connection_at_start
    ):
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

    def test_send_email_sends_errs(
        self, mocker, mock_configuration, dbsession, reset_connection_at_start
    ):
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

    def test_smtp_disconnected(
        self,
        mocker,
        mock_configuration,
        dbsession,
        set_username_and_password,
        reset_connection_at_start,
    ):
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

        smtp.connection.connect.assert_has_calls([call("mailhog", 1025)])
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

    def test_smtp_init_connect_fail(
        self, mocker, mock_configuration, dbsession, reset_connection_at_start
    ):
        m = MagicMock()
        mocker.patch("smtplib.SMTP", side_effect=SMTPConnectError(123, "abc"))
        email = Email(
            to_addr="test_to@codecov.io",
            from_addr="test_from@codecov.io",
            subject="Test subject",
            text="test text",
            html="test html",
        )

        with pytest.raises(
            SMTPServiceError, match="Error starting connection for SMTPService"
        ):
            smtp = SMTPService()

    def test_smtp_disconnected_fail(
        self, mocker, mock_configuration, dbsession, reset_connection_at_start
    ):
        m = MagicMock()
        m.configure_mock(
            **{
                "noop.side_effect": SMTPServerDisconnected(),
                "connect.side_effect": SMTPConnectError(123, "abc"),
            }
        )
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

        with pytest.raises(
            SMTPServiceError, match="Error starting connection for SMTPService"
        ):
            smtp = SMTPService()
            smtp.send(email)

    @pytest.mark.parametrize(
        "fn, err_msg, side_effect",
        [
            (
                "starttls",
                "Error doing STARTTLS command on SMTP",
                SMTPResponseException(123, "abc"),
            ),
            (
                "login",
                "SMTP server did not accept username/password combination",
                SMTPAuthenticationError(123, "abc"),
            ),
        ],
    )
    def test_smtp_tls_not_supported(
        self,
        caplog,
        mocker,
        mock_configuration,
        dbsession,
        reset_connection_at_start,
        set_username_and_password,
        fn,
        err_msg,
        side_effect,
    ):
        m = MagicMock()
        m.configure_mock(**{f"{fn}.side_effect": side_effect})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        with caplog.at_level(logging.WARNING):
            with pytest.raises(SMTPServiceError, match=err_msg):
                smtp = SMTPService()

        assert err_msg in caplog.text

    @pytest.mark.parametrize(
        "fn, err_msg",
        [
            (
                "starttls",
                "Server does not support TLS, continuing initialization of SMTP connection",
            ),
            (
                "login",
                "Server does not support AUTH, continuing initialization of SMTP connection",
            ),
        ],
    )
    def test_smtp_not_supported(
        self,
        caplog,
        mocker,
        mock_configuration,
        dbsession,
        reset_connection_at_start,
        set_username_and_password,
        fn,
        err_msg,
    ):
        m = MagicMock()
        m.configure_mock(**{f"{fn}.side_effect": SMTPNotSupportedError()})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        with caplog.at_level(logging.WARNING):
            smtp = SMTPService()

        assert err_msg in caplog.text
