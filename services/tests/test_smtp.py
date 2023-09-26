from ssl import create_default_context
from unittest.mock import MagicMock, call

from services.smtp import get_smtp_service


class TestSMTP(object):
    def test_correct_init(self, mocker, mock_configuration):
        mocker.patch("smtplib.SMTP")
        m = mocker.patch("ssl.create_default_context", return_value=MagicMock())
        service = get_smtp_service()
        service._conn.starttls.assert_called_with(context=m.return_value)

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
