import logging
import smtplib
import ssl

from shared.config import get_config

from helpers.email import Email

log = logging.getLogger(__name__)


class SMTPServiceError(Exception):
    ...


class SMTPService:
    connection = None

    @classmethod
    def active(cls):
        return cls.connection is not None

    @property
    def extra_dict(self):
        return {self.host, self.port, self.username}

    def _load_config(self):
        if get_config("services", "smtp", default={}) == {}:
            return False
        self.host = get_config("services", "smtp", "host", default="mailhog")
        self.port = get_config("services", "smtp", "port", default=1025)
        self.username = get_config("services", "smtp", "username", default=None)
        self.password = get_config("services", "smtp", "password", default=None)
        self.ssl_context = ssl.create_default_context()
        return True

    def make_connection(self):
        try:
            SMTPService.connection.connect(self.host, self.port)
        except smtplib.SMTPConnectError as exc:
            raise SMTPServiceError("Error starting connection for SMTPService") from exc
        try:
            SMTPService.connection.starttls(context=self.ssl_context)
        except smtplib.SMTPNotSupportedError:
            log.warning(
                "Server does not support TLS, continuing initialization of SMTP connection",
                extra=self.extra_dict,
            )
        if self.username and self.password:
            try:
                SMTPService.connection.login(self.username, self.password)
            except smtplib.SMTPNotSupportedError:
                log.warning(
                    "Server does not support auth, continuing initialization of SMTP connection",
                    extra=self.extra_dict,
                )

    def __init__(self):
        if not self._load_config():
            log.warning("Unable to load SMTP config")
            return
        if SMTPService.connection is None:
            try:
                SMTPService.connection = smtplib.SMTP(
                    host=self.host,
                    port=self.port,
                )
            except smtplib.SMTPConnectError as exc:
                raise SMTPServiceError(
                    "Error starting connection for SMTPService"
                ) from exc

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
            except smtplib.SMTPResponseException as exc:
                raise SMTPServiceError("Error doing STARTTLS command on SMTP") from exc

            if self.username and self.password:
                try:
                    SMTPService.connection.login(self.username, self.password)
                except smtplib.SMTPNotSupportedError:
                    log.warning(
                        "Server does not support auth, continuing initialization of SMTP connection",
                        extra=self.extra_dict,
                    )
                except smtplib.SMTPAuthenticationError as exc:
                    raise SMTPServiceError(
                        "SMTP server did not accept username/password combination"
                    ) from exc

    def send(self, email: Email):
        if not SMTPService.connection:
            return "Connection was not initialized"
        try:
            SMTPService.connection.noop()
        except smtplib.SMTPServerDisconnected:
            self.make_connection()  # reconnect if disconnected
        try:
            errs = SMTPService.connection.send_message(
                email.message,
            )
            if len(errs) != 0:
                err_msg = " ".join(
                    list(map(lambda err_tuple: f"{err_tuple[0]} {err_tuple[1]}", errs))
                )
                raise SMTPServiceError(err_msg)
        except smtplib.SMTPRecipientsRefused as exc:
            log.warning("All recipients were refused", extra=self.extra_dict)
            raise SMTPServiceError("All recipients were refused") from exc
        except smtplib.SMTPSenderRefused as exc:
            log.warning("Sender was refused", extra=self.extra_dict)
            raise SMTPServiceError("Sender was refused") from exc
        except smtplib.SMTPDataError as exc:
            log.warning(
                "The SMTP server did not accept the data", extra=self.extra_dict
            )
            raise SMTPServiceError("The SMTP server did not accept the data") from exc
