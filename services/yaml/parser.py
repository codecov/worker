from yaml import safe_load
from yaml.scanner import ScannerError
from services.yaml.exceptions import InvalidYamlException


def parse_yaml_file(content):
    try:
        return safe_load(content)
    except ScannerError:
        raise InvalidYamlException()
