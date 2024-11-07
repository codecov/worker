import pytest
import requests

from database.tests.factories import OwnerFactory
from services.smtp import SMTPService
from tasks.send_email import SendEmailTask

mock_smtp_config = {}

to_addr = "test_to@codecov.io"
username = "test_username"


@pytest.mark.integration
class TestSendEmailTask:
    def test_send_email_integration(
        self,
        mocker,
        dbsession,
        mock_storage,
        mock_redis,
        mock_configuration,
    ):
        SMTPService.connection = None
        tls = mocker.patch("smtplib.SMTP.starttls")
        login = mocker.patch("smtplib.SMTP.login")
        owner = OwnerFactory.create(email=to_addr, username=username)
        dbsession.add(owner)
        dbsession.flush()
        task = SendEmailTask()

        # make sure mailhog is not storing any other messages before
        # running this test
        res = requests.delete(
            "http://mailhog:8025/api/v1/messages",
        )

        assert res.status_code == 200

        result = task.run_impl(
            dbsession,
            owner.email,
            "TestSubject",
            "test",
            "test@codecov.io",
            username=owner.username,
        )

        assert result["email_successful"] == True
        assert result["err_msg"] is None

        res = requests.get(
            "http://mailhog:8025/api/v2/messages",
        )

        res = res.json()
        mail = res["items"][0]
        assert mail["To"] == [
            {
                "Domain": "codecov.io",
                "Mailbox": "test_to",
                "Params": "",
                "Relays": None,
            }
        ]
        assert mail["From"] == {
            "Domain": "codecov.io",
            "Mailbox": "test",
            "Params": "",
            "Relays": None,
        }

        mail_body = mail["Content"]["Body"].splitlines()
        assert mail_body[1:6] == [
            'Content-Type: text/plain; charset="utf-8"',
            "Content-Transfer-Encoding: 7bit",
            "",
            "Test template test_username",
            "",
        ]
        assert mail_body[7:-1] == [
            'Content-Type: text/text/html; charset="utf-8"',
            "Content-Transfer-Encoding: 7bit",
            "MIME-Version: 1.0",
            "",
            "<!DOCTYPE html>",
            '<html lang="en">',
            "",
            "<head>",
            '    <meta charset="UTF-8">',
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
            "    <title>Document</title>",
            "</head>",
            "",
            "<body>",
            "    <p>",
            "        test template test_username",
            "    </p>",
            "</body>",
            "",
            "</html>",
            "",
        ]
        assert res["count"] == 1
