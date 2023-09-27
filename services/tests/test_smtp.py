from ssl import create_default_context
from unittest.mock import MagicMock, call

from helpers.email import Email
from services.smtp import get_smtp_service


class TestSMTP(object):
    def test_correct_init(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        mock_configuration._params["services"]["smtp"]["username"] = "test_username"
        mock_configuration._params["services"]["smtp"]["password"] = "test_password"
        m = mocker.patch("ssl.create_default_context", return_value=MagicMock())
        service = get_smtp_service()
        service._conn.starttls.assert_called_with(context=m.return_value)
        service._conn.login.assert_called_with("test_username", "test_password")

    def test_idempotent_service(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        first = get_smtp_service()
        second = get_smtp_service()
        assert id(first) == id(second)

    def test_idempotent_connection(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        first = get_smtp_service()
        first_conn = first._conn
        second = get_smtp_service()
        second_conn = second._conn
        assert id(first_conn) == id(second_conn)

    def test_empty_config(self, mocker, mock_configuration):
        del mock_configuration._params["services"]["smtp"]
        service = get_smtp_service()
        assert service is None

    def test_send(self, mocker, mock_configuration):
        email = Email(
            to_addr="test_to@codecov.io",
            from_addr="test_from@codecov.io",
            subject="Test subject",
            text="test text",
            html="test html",
        )

        smtp = get_smtp_service()
        smtp.send(email=email)

        smtp._conn.send_message.assert_called_with(email.message)
