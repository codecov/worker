import smtplib
import ssl
from functools import cached_property

from shared.config import get_config

from helpers.email import Email

_smtp_service = None


def get_smtp_service():
    if len(get_config("services", "smtp", default={})) == 0:
        return None
    return _get_cached_smtp_service()


def _get_cached_smtp_service():
    global _smtp_service
    if _smtp_service is None:
        _smtp_service = SMTPService()
    return _smtp_service


class SMTPService:
    def __init__(self):
        self.host = get_config("services", "smtp", "host", default="mailhog")
        self.port = get_config("services", "smtp", "port", default=1025)
        self.username = get_config("services", "smtp", "username", default=None)
        self.password = get_config("services", "smtp", "password", default=None)
        self.ssl_context = ssl.create_default_context()

        self._conn = smtplib.SMTP(
            host=self.host,
            port=self.port,
        )
        self._conn.starttls(context=self.ssl_context)
        if self.username and self.password:
            self._conn.login(self.username, self.password)

    def send(self, email: Email):
        return self._conn.send_message(
            email.message,
        )
