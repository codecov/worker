import smtplib
import ssl
from functools import cached_property

from shared.config import get_config

from helpers.email import Email

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
        self.config = get_config("services", "smtp", default={})
        self._conn = None

    @property
    def _smtp_object(self):
        return smtplib.SMTP_SSL if "ssl" in self.config else smtplib.SMTP

    @cached_property
    def _ssl_context(self):
        certfile = self.config.get("ssl", {}).get("certfile", "")
        keyfile = self.config.get("ssl", {}).get("keyfile", "")
        if certfile or keyfile:
            ssl_context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.load_cert_chain(certfile, keyfile)
            return ssl_context
        else:
            return ssl.create_default_context()

    def open(self):
        if self._conn:
            return

        self._conn = self._smtp_object(
            host=self.config["host"],
            port=self.config["port"],
        )
        self._conn.starttls(context=self._ssl_context)

        self._conn.login(self.config["username"], self.config["password"])

    def close(self):
        if self._conn:
            self._conn.quit()
            self._conn = None

    def send(self, email: Email):
        return self._conn.send_message(
            email.message,
        )
