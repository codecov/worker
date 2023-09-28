from smtplib import SMTPDataError, SMTPRecipientsRefused, SMTPSenderRefused
from ssl import create_default_context
from unittest.mock import MagicMock, call, patch

from helpers.email import Email
from services.smtp import SMTPService

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
        mocker.patch("smtplib.SMTP")
        first = SMTPService()
        firstconnection = first.connection
        second = SMTPService()
        secondconnection = second.connection
        assert id(firstconnection) == id(secondconnection)

    def test_empty_config(self, mocker, mock_configuration):
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
        m = MagicMock()
        m.configure_mock(**{"send_message.side_effect": SMTPRecipientsRefused(to_addr)})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        err_msg = smtp.send(email=test_email)
        assert err_msg == "All recipients were refused"

    def test_send_email_sender_refused(self, mocker, mock_configuration, dbsession):
        m = MagicMock()
        m.configure_mock(
            **{"send_message.side_effect": SMTPSenderRefused(123, "", to_addr)}
        )
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        err_msg = smtp.send(email=test_email)

        assert err_msg == "Sender was refused"

    def test_send_email_data_error(self, mocker, mock_configuration, dbsession):
        m = MagicMock()
        m.configure_mock(**{"send_message.side_effect": SMTPDataError(123, "")})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        err_msg = smtp.send(email=test_email)

        assert err_msg == "The SMTP server did not accept the data"

    def test_send_email_sends_errs(self, mocker, mock_configuration, dbsession):
        m = MagicMock()
        m.configure_mock(**{"send_message.return_value": [(123, "abc"), (456, "def")]})
        mocker.patch(
            "smtplib.SMTP",
            return_value=m,
        )

        smtp = SMTPService()

        err_msg = smtp.send(email=test_email)

        assert err_msg == "123 abc 456 def"
