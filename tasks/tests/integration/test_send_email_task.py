import pytest
import requests
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from database.tests.factories import OwnerFactory
from tasks.send_email import SendEmailTask

mock_smtp_config = {}

to_addr = "test_to@codecov.io"
username = "test_username"


@pytest.mark.integration
class TestSendEmailTask:
    @pytest.mark.asyncio
    async def test_send_email_integration(
        self,
        mocker,
        dbsession,
        mock_configuration,
        mock_storage,
        mock_redis,
    ):
        owner = OwnerFactory.create(email=to_addr, username=username)
        dbsession.add(owner)
        dbsession.flush()
        task = SendEmailTask()
        mailhog_container = (
            DockerContainer("mailhog/mailhog:latest")
            .with_bind_ports(1025, 1025)
            .with_bind_ports(8025, 9025)
        )
        with mailhog_container as container:
            delay = wait_for_logs(container, "Creating API v2 with WebPath:")
            result = await task.run_async(
                dbsession,
                owner.ownerid,
                "test",
                "test@codecov.io",
                "TestSubject",
                username=owner.username,
            )

            assert result["email_successful"] == True
            assert result["err_msg"] is None

            res = requests.get(
                "http://localhost:9025/api/v2/messages",
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
