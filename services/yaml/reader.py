import logging
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Any, Mapping

from shared.yaml.user_yaml import UserYaml

log = logging.getLogger(__name__)


"""
    Carries tools to help reading of a already-processed user yaml
"""


def read_yaml_field(yaml_dict: UserYaml, keys, _else=None) -> Any:
    log.debug("Field %s requested", keys)
    try:
        for key in keys:
            if hasattr(yaml_dict, "__getitem__"):
                yaml_dict = yaml_dict[key]
            else:
                yaml_dict = getattr(yaml_dict, key)
        return yaml_dict
    except (TypeError, AttributeError, KeyError):
        return _else


def get_minimum_precision(yaml_dict: Mapping[str, Any]) -> Decimal:
    precision = read_yaml_field(yaml_dict, ("coverage", "precision"), 2)
    return Decimal("0.1") ** precision


def round_number(yaml_dict: UserYaml, number: Decimal):
    rounding = read_yaml_field(yaml_dict, ("coverage", "round"), "nearest")
    quantizer = get_minimum_precision(yaml_dict)
    if rounding == "up":
        return number.quantize(quantizer, rounding=ROUND_CEILING)
    if rounding == "down":
        return number.quantize(quantizer, rounding=ROUND_FLOOR)
    return number.quantize(quantizer, rounding=ROUND_HALF_EVEN)


def get_paths_from_flags(yaml_dict: UserYaml, flags):
    if flags:
        res = []
        for flag in flags:
            flag_configuration = yaml_dict.get_flag_configuration(flag)
            if flag_configuration is not None:
                paths_from_flag = flag_configuration.get("paths")
                if paths_from_flag is None:
                    # flag is implicitly associated with all paths, so no filter here
                    return []
                res.extend(paths_from_flag)
        return list(set(res))
    else:
        return []
