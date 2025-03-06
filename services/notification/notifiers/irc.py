import logging
import socket
from io import BytesIO
from typing import Any, List, Mapping

from database.enums import Notification
from services.notification.notifiers.generics import Comparison, StandardNotifier

log = logging.getLogger(__name__)


class IRCClient(object):
    def __init__(self, server) -> None:
        self.server = server
        server = tuple(self.server.split(":")) + (6667,)
        self.con = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.con.settimeout(1)
        self.con.connect((server[0], int(server[1])))

    def send(self, message: str):
        message = message + "\r\n"
        return self.con.send(message.encode())

    def close(self) -> None:
        self.con.close()

    def receive_everything(self) -> List[str]:
        received_messages = BytesIO()
        try:
            while 1:
                data = self.con.recv(1024)
                received_messages.write(data)
                if not data:
                    break
        except socket.timeout:
            log.debug("Message sent")
        final_data = received_messages.getvalue().decode().split("\r\n")
        for line in final_data:
            if line.startswith("PING"):
                message_to_respond = line.split(" ")[1]
                self.send(f"PONG {message_to_respond}")
        return final_data


class IRCNotifier(StandardNotifier):
    BASE_MESSAGE = " ".join(
        [
            "Coverage for {owner_username}/{repo_name}",
            "{comparison_string}on `{head_branch}` is `{head_totals_c}%`",
            "via `{head_short_commitid}`",
        ]
    )

    COMPARISON_STRING = "*{compare_message}* `{compare_notation}{compare_coverage}%` "

    @property
    def notification_type(self) -> Notification:
        return Notification.irc

    def send_actual_notification(self, data: Mapping[str, Any]) -> dict:
        # https://github.com/travis-ci/travis-tasks/blob/94c97165d7ecf89d986609614667ae86dff7e9ce/lib/travis/addons/irc/client.rb
        message = data["message"]
        con = IRCClient(self.notifier_yaml_settings["server"])
        if self.notifier_yaml_settings.get("password"):
            command_to_send = "PASS %s" % self.notifier_yaml_settings["password"]
            con.send(command_to_send)
        con.send("USER codecov codecov codecov :codecov")
        con.send("NICK codecov")
        con.receive_everything()
        if self.notifier_yaml_settings.get("nickserv_password"):
            nickserv_password = self.notifier_yaml_settings["nickserv_password"]
            command_to_send = f"PRIVMSG NickServ :IDENTIFY {nickserv_password}"
            con.send(command_to_send)
        con.receive_everything()
        if self.notifier_yaml_settings["channel"][0] == "#":
            command = "JOIN %s \n" % self.notifier_yaml_settings["channel"]
            con.send(command)
        con.receive_everything()

        status = (
            "NOTICE" if self.notifier_yaml_settings.get("notice", True) else "PRIVMSG"
        )
        channel = self.notifier_yaml_settings["channel"]
        message_to_send = f"{status} {channel} :{message} "
        con.send(message_to_send)
        con.receive_everything()
        con.close()
        return {"successful": True, "reason": None}

    def build_payload(self, comparison: Comparison) -> dict:
        return {"message": self.generate_message(comparison)}
