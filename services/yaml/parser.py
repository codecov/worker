from yaml import safe_load
from yaml.error import YAMLError
from shared.validation.yaml import validate_yaml
from shared.validation.exceptions import InvalidYamlException


def parse_yaml_file(content):
    try:
        yaml_dict = safe_load(content)
    except YAMLError as e:
        raise InvalidYamlException("invalid_yaml", e)
    if yaml_dict is None:
        return None
    return validate_yaml(yaml_dict, show_secrets=True)
