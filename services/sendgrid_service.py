import json
import logging
import os
from pathlib import Path

import requests
from yaml import YAMLError, safe_load

here = Path(__file__)
folder = here.parent

log = logging.getLogger(__name__)


class Sendgrid(object):

    yaml_location = "email_config.yaml"
    base_url = "https://api.sendgrid.com/v3/"
    contacts_path = "marketing/contacts"
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")

    request_headers = {
        "Authorization": "Bearer " + SENDGRID_API_KEY,
        "Content-Type": "application/json",
    }

    def __init__(self, list_type=None):
        self.config = None
        self.list_type = list_type
        self.load_config(list_type)

    def load_config(self, list_type):
        with open(folder / self.yaml_location, "r") as stream:
            try:
                data = safe_load(stream)
                self.config = data[list_type]
            except YAMLError as e:
                log.error("Unable to read email config file")
            except KeyError as e:
                log.error("Unable to find list_type %s", list_type)

    def add_to_list(self, email):
        if self.config is None or self.config.get("list_id") is None:
            return None

        data = {
            "list_ids": [self.config.get("list_id")],
            "contacts": [{"email": email}],
        }
        r = requests.put(
            self.base_url + self.contacts_path,
            data=json.dumps(data),
            headers=self.request_headers,
        )
        return r.json()

    def send_email(self, owner):
        if self.list_type == "end-of-trial":
            return self.add_to_list(owner.email)
