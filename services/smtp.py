import logging
import smtplib
import ssl

from shared.config import get_config

from helpers.email import Email

log = logging.getLogger(__name__)


class SMTPService:
    connection = None

    @classmethod
    def active(cls):
        return cls.connection is not None

    def _load_config(self):
        if get_config("services", "smtp", default={}) == {}:
            return False
        self.host = get_config("services", "smtp", "host", default="mailhog")
        self.port = get_config("services", "smtp", "port", default=1025)
        self.username = get_config("services", "smtp", "username", default=None)
        self.password = get_config("services", "smtp", "password", default=None)
        self.ssl_context = ssl.create_default_context()
        return True

    def __init__(self):
        if not self._load_config():
            log.warning("Unable to load SMTP config")
            return
        if SMTPService.connection is None:
            SMTPService.connection = smtplib.SMTP(
                host=self.host,
                port=self.port,
            )

            # only necessary if SMTP server supports TLS and authentication,
            # for example mailhog does not need these two steps
            try:
                SMTPService.connection.starttls(context=self.ssl_context)
            except smtplib.SMTPNotSupportedError:
                log.warning(
                    "Server does not support TLS, continuing initialization of SMTP connection",
                    extra=dict(
                        host=self.host,
                        port=self.port,
                        username=self.username,
                        password=self.password,
                    ),
                )

            if self.username and self.password:
                try:
                    SMTPService.connection.login(self.username, self.password)
                except smtplib.SMTPNotSupportedError:
                    log.warning(
                        "Server does not support auth, continuing initialization of SMTP connection",
                        extra=dict(
                            host=self.host,
                            port=self.port,
                            username=self.username,
                            password=self.password,
                        ),
                    )

    def send(self, email: Email):
        err_msg = None
        if not SMTPService.connection:
            return "Connection was not initialized"
        try:
            errs = SMTPService.connection.send_message(
                email.message,
            )
            if len(errs) != 0:
                err_msg = " ".join(
                    list(map(lambda err_tuple: f"{err_tuple[0]} {err_tuple[1]}", errs))
                )
        except smtplib.SMTPRecipientsRefused:
            err_msg = "All recipients were refused"
        except smtplib.SMTPSenderRefused:
            err_msg = "Sender was refused"
        except smtplib.SMTPDataError:
            err_msg = "The SMTP server did not accept the data"

        return err_msg
