import socket

from services.notification.notifiers.irc import IRCNotifier


class TestIRCNotifier(object):
    def test_build_payload(self, dbsession, mock_configuration, sample_comparison):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        notifier = IRCNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"server": ""},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        result = notifier.build_payload(comparison)
        commit = comparison.head.commit
        repository = commit.repository
        text = f"Coverage for {repository.slug} *increased* `+10.00%` on `new_branch` is `60.00000%` via `{commit.commitid[:7]}`"
        expected_result = {"message": text}
        assert result == expected_result

    def test_send_actual_notification(
        self, dbsession, mock_configuration, sample_comparison, mocker
    ):
        mocked_connection = mocker.patch(
            "services.notification.notifiers.irc.socket.socket"
        ).return_value
        mocked_connection.recv.side_effect = [
            b":956adb1eca91.example.com NOTICE * :*** Looking up your hostname...\r\n",
            b"PING :fhkFTdCsVx\r\n:956adb1eca91.example.com NOTICE codecov :*** I...\r\n",
            b":956adb1eca91.example.com NOTICE codecov :*** Could not resolve you...\r\n",
            socket.timeout,
            b":956adb1eca91.example.com 451 codecov PRIVMSG :You have not registe...\r\n",
            b":956adb1eca91.example.com 001 codecov :Welcome to the Omega IRC Net... USE",
            b"RLEN=11 WHOX :are supported by this server\r\n:956adb1eca91.example...\\ |",
            b" |_) | _| |_  | | \\ \\ | |____ | (_| |\r\n:956adb1eca91.example.co...6adb",
            b"1eca91.example.com 372 codecov :-            \\ \\   `.  `-._      ...    ",
            b"    \\\r\n:956adb1eca91.example.com 372 codecov :-       |   * IRC:...----",
            b"-----------------------\r\n:956adb1eca91.example.com 372 codecov :-... war",
            b"m welcome from the InspIRCd-Docker Team, too!\r\n:956adb1eca91.exam...\r\n",
            b":NickServ!services@services.localhost.net NOTICE codecov :This nick...\r\n",
            b"",
            socket.timeout,
            b":codecov!codecov@172.22.0.1 JOIN :#samplechannel\r\n:956adb1eca91.e...\r\n",
            socket.timeout,
            socket.timeout,
        ]
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        notifier = IRCNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "server": "ircserver",
                "channel": "#samplechannel",
                "password": "s3cret",
                "nickserv_password": "password",
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        commit = comparison.head.commit
        repository = commit.repository
        text = f"Coverage for {repository.slug} *increased* `+10.00%` on `new_branch` is `60.00000%` via `{commit.commitid[:7]}`"
        data = {"message": text}
        result = notifier.send_actual_notification(data)
        expected_result = {"successful": True, "reason": None}
        assert result == expected_result
