import os

from yaml import load as yaml_load
import collections

default_config = {
    'services': {
        'minio': {
            'access_key_id': 'codecov-default-key',
            'secret_access_key': 'codecov-default-secret',
            'verify_ssl': False
        }
    }
}


def update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


class ConfigHelper(object):

    def __init__(self):
        self._params = None

    @property
    def params(self):
        if self._params is None:
            content = self.yaml_content()
            final_result = update(default_config, content)
            self.set_params(final_result)
        return self._params

    def set_params(self, val):
        self._params = val

    def get(self, *args, **kwargs):
        current_p = self.params
        for el in args:
            current_p = current_p[el]
        return current_p

    def yaml_content(self):
        yaml_path = os.getenv('CODECOV_YML', '/config/codecov.yml')
        with open(yaml_path, 'r') as c:
            return yaml_load(c.read())


config = ConfigHelper()


def get_config(*path, default=None):
    try:
        return config.get(*path)
    except Exception:
        return default


def get_verify_ssl(service):
    verify = get_config(service, 'verify_ssl')
    if verify is False:
        return False
    return get_config(service, 'ssl_pem') or os.getenv('REQUESTS_CA_BUNDLE')
