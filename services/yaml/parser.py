from typing import Dict, Optional

from shared.validation.exceptions import InvalidYamlException
from shared.validation.yaml import validate_yaml
from yaml import safe_load
from yaml.error import YAMLError


def parse_yaml_file(content: str, show_secrets_for) -> Optional[Dict]:
    try:
        yaml_dict = safe_load(content)
    except YAMLError as e:
        raise InvalidYamlException("invalid_yaml", e)
    if yaml_dict is None:
        return None
    return validate_yaml(yaml_dict, show_secrets_for=show_secrets_for)
