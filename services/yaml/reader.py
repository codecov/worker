import logging
from decimal import Decimal
from typing import Any, List, Mapping

from shared.yaml.user_yaml import UserYaml

from helpers.components import Component
from helpers.number import precise_round

log = logging.getLogger(__name__)


"""
    Carries tools to help reading of a already-processed user yaml
"""


def read_yaml_field(yaml_dict: UserYaml | Mapping[str, Any], keys, _else=None) -> Any:
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


def round_number(yaml_dict: UserYaml, number: Decimal) -> Decimal:
    rounding = read_yaml_field(yaml_dict, ("coverage", "round"), "nearest")
    precision = read_yaml_field(yaml_dict, ("coverage", "precision"), 2)
    return precise_round(number, precision=precision, rounding=rounding)


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


def get_components_from_yaml(yaml: UserYaml) -> List[Component]:
    component_definitions = read_yaml_field(yaml, ("component_management",))
    if not component_definitions:
        return []
    # Default set of rules that is overriden by individual components.
    # The individual components inherit the values from default_definition if they don't have a particular key defined in the default rules
    default_definition = component_definitions.get("default_rules", {})

    individual_components = list(
        map(
            lambda component_dict: Component.from_dict(
                {**default_definition, **component_dict}
            ),
            component_definitions.get("individual_components", []),
        )
    )
    return individual_components
