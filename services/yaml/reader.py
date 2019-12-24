import logging
from typing import Mapping, Any
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN

log = logging.getLogger(__name__)


"""
    Carries tools to help reading of a already-processed user yaml
"""


def read_yaml_field(yaml_dict, keys, _else=None):
    log.debug("Field %s requested", keys)
    try:
        for key in keys:
            if hasattr(yaml_dict, '__getitem__'):
                yaml_dict = yaml_dict[key]
            else:
                yaml_dict = getattr(yaml_dict, key)
        return yaml_dict
    except (AttributeError, KeyError):
        return _else


def round_number(yaml_dict: Mapping[str, Any], number: Decimal):
    precision = read_yaml_field(yaml_dict, ('coverage', 'precision'), 2)
    rounding = read_yaml_field(yaml_dict, ('coverage', 'round'), 'nearest')
    quantizer = Decimal('0.1')**precision
    if rounding == 'up':
        return number.quantize(quantizer, rounding=ROUND_CEILING)
    if rounding == 'down':
        return number.quantize(quantizer, rounding=ROUND_FLOOR)
    print(quantizer)
    return number.quantize(quantizer, rounding=ROUND_HALF_EVEN)


def get_paths_from_flags(yaml_dict: Mapping[str, Any], flags):
    if flags:
        res = []
        for flag in flags:
            res.extend(read_yaml_field(yaml_dict, ('flags', flag, 'paths')) or [])
        return list(set(res))
    else:
        return []
