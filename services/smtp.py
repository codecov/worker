import smtplib
import ssl
from functools import cached_property

from helpers.email import Email
from helpers.environment import Environment, get_current_env
from shared.config import get_config


_smtp_service = None


def get_smtp_service():
    return _get_cached_smtp_service()


def _get_cached_smtp_service():
    global _smtp_service
    if _smtp_service is None:
        _smtp_service = SMTPService()
    return _smtp_service


class SMTPService:
    def __init__(self):
        self.host = get_config("services", "smtp", "host")
        self.port = get_config("services", "smtp", "port")
        self.username = get_config("services", "smtp", "username", default=None)
        self.password = get_config("services", "smtp", "password", default=None)
        self.certfile = get_config("services", "smtp", "ssl", "certfile", default=None)
        self.keyfile = get_config("services", "smtp", "ssl", "keyfile", default=None)
        self._conn = None

    @property
    def _smtp_object(self):
        return smtplib.SMTP_SSL if (self.certfile and self.keyfile) else smtplib.SMTP

    @cached_property
    def _ssl_context(self):
        if self.certfile and self.keyfile:
            ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.load_cert_chain(self.certfile, self.keyfile)
            return ssl_context
        else:
            return ssl.create_default_context()

    def open(self):
        if self._conn:
            return
        self._conn = self._smtp_object(
            host=self.host,
            port=self.port,
        )
        if get_current_env() != Environment.local:
            self._conn.starttls(context=self._ssl_context)

        if self.username and self.password:
            self._conn.login(self.username, self.password)

    def close(self):
        if self._conn:
            self._conn.quit()
            self._conn = None

    def send(self, email: Email):
        return self._conn.send_message(
            email.message,
        )
