from yaml import safe_load
from yaml.scanner import ScannerError
from services.yaml.exceptions import InvalidYamlException
from services.yaml.validation import validate_yaml


def parse_yaml_file(content):
    try:
        yaml_dict = safe_load(content)
    except ScannerError:
        raise InvalidYamlException()
    if yaml_dict is None:
        return None
    return validate_yaml(yaml_dict)
