import os
import json
import requests
import logging

from pathlib import Path
from yaml import safe_load, YAMLError

here = Path(__file__)
folder = here.parent

log = logging.getLogger(__name__)

class Sendgrid(object):
    
    yaml_location = "email_config.yaml"
    base_url = "https://api.sendgrid.com/v3/"
    contacts_path = "marketing/contacts"
    SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY', '')

    request_headers = {
        'Authorization': 'Bearer ' + SENDGRID_API_KEY,
        'Content-Type': 'application/json'
    }

    def __init__(self, email_type):
        self.email_type = email_type
        self.load_config(email_type)

    def load_config(self, email_type):
        with open(folder / self.yaml_location, 'r') as stream:
            try:
                data = safe_load(stream)
                self.config = data[email_type]
            except YAMLError as e:
                log.error('Unable to read email config file')

    def add_to_list(self, email):
        data = {
            "list_ids":[ self.config.get('list_id') ],
            "contacts": [ { "email": email } ]
        }
        r = requests.put(self.base_url+self.contacts_path, data=json.dumps(data), headers=self.request_headers)
        return r.json()

    def send_email(self, owner):
        if self.email_type == 'end-of-trial':
            return self.add_to_list(owner.email)
