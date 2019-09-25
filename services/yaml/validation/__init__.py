import logging

from schema import Schema, Optional, Or, And, SchemaError, Regex
from services.yaml.exceptions import InvalidYamlException
from services.yaml.validation.helpers import (
    PercentSchemaField, BranchSchemaField, UserGivenBranchRegex, LayoutStructure,
    PathPatternSchemaField, UserGivenSecret, CoverageRangeSchemaField, CustomFixPathSchemaField
)

log = logging.getLogger(__name__)


def validate_yaml(inputted_yaml_dict):
    """Receives a user-given yaml dict, validates and normalizes the fields for
        usage by other code

    Args:
        inputted_yaml_dict (dict): The yaml as parsed by a yaml parser and turned into a dict

    Returns:
        dict: A deep copy of the dict with the fields normalized

    Raises:
        InvalidYamlException: If the yaml inputted by the user is not valid
    """
    pre_process_yaml(inputted_yaml_dict)
    try:
        result = user_yaml_schema.validate(inputted_yaml_dict)
        return post_process(result)
    except SchemaError as e:
        log.warning(
            "Unable to validate yaml", extra=dict(user_input=inputted_yaml_dict),
            exc_info=True
        )
        raise InvalidYamlException(e)


def post_process(validated_yaml_dict):
    """Does any needed post-processings

    Args:
        validated_yaml_dict (dict): The dict after validated

    Returns:
        (dict): The post-processed dict to be used

    """
    return validated_yaml_dict


def pre_process_yaml(inputted_yaml_dict):
    """
        Changes the inputted_yaml_dict in-place with compatibility changes that need to be done

    Args:
        inputted_yaml_dict (dict): The yaml dict inputted by the user
    """
    coverage = inputted_yaml_dict.get('coverage', {})
    if 'flags' in coverage:
        inputted_yaml_dict['flags'] = coverage.pop('flags')
    if 'parsers' in coverage:
        inputted_yaml_dict['parsers'] = coverage.pop('parsers')
    if 'ignore' in coverage:
        inputted_yaml_dict['ignore'] = coverage.pop('ignore')
    if 'fixes' in coverage:
        inputted_yaml_dict['fixes'] = coverage.pop('fixes')
    if 'codecov' in inputted_yaml_dict and 'notify' in inputted_yaml_dict['codecov']:
        if 'require_ci_to_pass' in inputted_yaml_dict['codecov']['notify']:
            val = inputted_yaml_dict['codecov']['notify'].pop('require_ci_to_pass')
            inputted_yaml_dict['codecov']['require_ci_to_pass'] = val


user_given_title = Regex(r'^[\w\-\.]+$')
flag_name = Regex(r'^[\w\.\-]{1,45}$')
percent_type = PercentSchemaField()
branch_structure = BranchSchemaField()
branches_regexp = Regex(r'')
user_given_regex = UserGivenBranchRegex()
layout_structure = LayoutStructure()
path_structure = PathPatternSchemaField()
base_structure = Or('parent', 'pr', 'auto')
branch = BranchSchemaField()
url = Regex(r'https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)')

notification_standard_attributes = {
    Optional('url'): Or(None, UserGivenSecret()),
    Optional('branches'): Or(None, [branches_regexp]),
    Optional('threshold'): Or(None, percent_type),
    Optional('message'): str,  # TODO (Thiago): Convert this to deal with handlebars
    Optional('flags'): Or(None, [flag_name]),
    Optional('base'): base_structure,
    Optional('only_pulls'): bool,
    Optional('paths'): Or(None, [path_structure])
}

status_standard_attributes = {
    Optional('branches'): Or(None, [user_given_regex]),
    Optional('if_no_uploads'): Or('success', 'failure', 'error', 'ignore'),
    Optional('if_not_found'): Or('success', 'failure', 'error', 'ignore'),
    Optional('if_ci_failed'): Or('success', 'failure', 'error', 'ignore'),
    Optional('skip_if_assumes'): bool,
    Optional('informational'): bool,
    Optional('disable_approx'): bool,
    Optional('target'): Or('auto', percent_type),
    Optional('threshold'): Or(None, percent_type),
    Optional('only_pulls'): bool,
    Optional('include_changes'): bool,
    Optional('base'): base_structure,
    Optional('measurement'): Or(None, 'line', 'statement', 'branch', 'method', 'complexity'),
    Optional('flags'): Or(None, [flag_name]),
    Optional('paths'): Or(None, [path_structure])
}

user_yaml_schema = Schema(
    {
        Optional('codecov'): {
            Optional('url'): url,
            Optional('token'): str,
            Optional('slug'): str,
            Optional('bot'): str,
            Optional('branch'): branch,
            Optional('ci'): [str],
            Optional('assume_all_flags'): bool,
            Optional('strict_yaml_branch'): str,
            Optional('max_report_age'): Or(str, int, bool),
            Optional('disable_default_path_fixes'): bool,
            Optional('require_ci_to_pass'): bool,
            Optional('allow_coverage_offsets'): bool,
            Optional('allow_pseudo_compare'): bool,
            Optional('archive'): {
                Optional('uploads'): bool
            },
            Optional('notify'): {
                Optional('after_n_builds'): int,
                Optional('countdown'): int,
                Optional('delay'): int,
                Optional('wait_for_ci'): bool,
                Optional('require_ci_to_pass'): bool  # [DEPRECATED]
            },
            Optional('ui'): {
                Optional('hide_density'): Or(bool, [str]),
                Optional('hide_complexity'): Or(bool, [str]),
                Optional('hide_contexual'): bool,
                Optional('hide_sunburst'): bool,
                Optional('hide_search'): bool
            }
        },
        Optional('coverage'): {
            Optional('precision'): And(int, lambda n: 0 <= n <= 99),
            Optional('round'): And(str, Or('down', 'up', 'nearest')),
            Optional('range'): CoverageRangeSchemaField(),
            Optional('notify'): {
                Optional('irc'): {
                    user_given_title: {
                        Optional('channel'): str,
                        Optional('server'): str,
                        Optional('password'): UserGivenSecret(),
                        Optional('nickserv_password'): UserGivenSecret(),
                        Optional('notice'): bool,
                        **notification_standard_attributes
                    }
                },  # TODO (Thiago): Implement this
                Optional('slack'): {
                    user_given_title: {
                        Optional('attachments'): layout_structure,
                        **notification_standard_attributes
                    }
                },  # TODO (Thiago): Implement this
                Optional('gitter'): {
                    user_given_title: {**notification_standard_attributes}
                },  # TODO (Thiago): Implement this
                Optional('hipchat'): {
                    user_given_title: {
                        Optional('card'): bool,
                        Optional('notify'): bool,
                        **notification_standard_attributes
                    }
                },  # TODO (Thiago): Implement this
                Optional('webhook'): {
                    user_given_title: {**notification_standard_attributes}
                },  # TODO (Thiago): Implement this
                Optional('email'): {
                    user_given_title: {
                        Optional('layout'): layout_structure,
                        'to': [And(str, UserGivenSecret())],
                        **notification_standard_attributes
                    }
                },  # TODO (Thiago): Implement this
            },
            Optional('status'): Or(
                bool,
                {
                    Optional('project'): Or(
                        bool,
                        {
                            user_given_title: Or(
                                None,
                                bool,
                                {
                                    Optional('target'): Or('auto', percent_type),
                                    Optional('include_changes'): Or('auto', percent_type),
                                    Optional('threshold'): percent_type,
                                    **status_standard_attributes
                                }
                            )
                        }
                    ),
                    Optional('patch'): Or(
                        bool,
                        {
                            user_given_title: Or(
                                None,
                                bool,
                                {
                                    Optional('target'): Or('auto', percent_type),
                                    Optional('include_changes'): Or('auto', percent_type),
                                    Optional('threshold'): percent_type,
                                    **status_standard_attributes
                                }
                            )
                        }
                    ),
                    Optional('changes'): Or(
                        bool,
                        {
                            user_given_title: Or(
                                None,
                                bool,
                                status_standard_attributes
                            )
                        }
                    ),
                },
            )
        },
        Optional('parsers'): {
            Optional('javascript'): {
                'enable_partials': bool
            },
            Optional('v1'): {
                'include_full_missed_files': bool  # [DEPRECATED]
            },
            Optional('gcov'): {
                'branch_detection': {
                    'conditional': bool,
                    'loop': bool,
                    'method': bool,
                    'macro': bool
                }
            }
        },
        Optional('ignore'): Or(None, [path_structure]),
        Optional('fixes'): Or(None, [CustomFixPathSchemaField()]),
        Optional('flags'): {
            user_given_title: {
                Optional('joined'): bool,
                Optional('required'): bool,
                Optional('ignore'): Or(None, [path_structure]),
                Optional('paths'): Or(None, [path_structure]),
                Optional('assume'): Or(bool, {'branches': Or(None, [user_given_regex])})
            }
        },
        Optional('comment'): Or(
            bool,
            {
                Optional('layout'): Or(None, layout_structure),
                Optional('require_changes'): bool,
                Optional('require_base'): bool,
                Optional('require_head'): bool,
                Optional('branches'): Or(None, [user_given_regex]),
                Optional('behavior'): Or('default', 'once', 'new', 'spammy'),
                Optional('flags'): Or(None, [flag_name]),  # DEPRECATED
                Optional('paths'): Or(None, [path_structure])  # DEPRECATED
            }
        ),
    }
)
