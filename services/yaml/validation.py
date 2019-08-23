import logging
import re

from schema import Schema, Optional, Or, And, SchemaError, Regex
from services.yaml.exceptions import InvalidYamlException
from covreports.encryption import StandardEncryptor

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
        log.exception("Unable to validate yaml", extra=dict(user_input=inputted_yaml_dict))
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


class CoverageRange(object):

    def validate(self, data):
        if '...' in data:
            splitter = '...'
        elif '..' in data:
            splitter = '..'
        else:
            raise SchemaError(f"{data} does not have the correct format")
        split_value = data.split(splitter)
        if len(split_value) != 2:
            raise SchemaError(f"{data} should have only two numbers")
        try:
            return (float(split_value[0]), float(split_value[1]))
        except ValueError:
            raise SchemaError(f"{data} should have numbers as the range limits")


class Percent(object):

    def validate(self, value):
        if value.endswith('%'):
            value = value.replace('%', '')
        return float(value)


class PathStructure(object):

    path_with_star_but_not_dot_star = re.compile(r'(?<!\.)\*')

    def input_type(self, value):
        reserved_chars = ['*', '$', ']', '[']
        if not any(x in value for x in reserved_chars):
            return 'closed_path'
        if '**' in value or '/*' in value:
            return 'glob'
        if '.*' in value:
            return 'regex'
        return 'glob'

    def translate(self, pat):
        """
            Translate a shell PATTERN to a regular expression.

            There is no way to quote meta-characters.

            This is copied from fnmatch.translate. If you could be
                so kind and see if they changed it since we copied,
                that would be very helpful, thanks.

            The only reason we copied (instead of importing and using),
                is that we needed to change behavior on **
        """

        i, n = 0, len(pat)
        res = ''
        while i < n:
            c = pat[i]
            i = i+1
            if c == '*':
                if i < n and pat[i] == '*':
                    res = res + '.*'
                    i = i + 1
                else:
                    res = res + r'[^\/]+'
            elif c == '?':
                res = res + '.'
            elif c == '[':
                j = i
                if j < n and pat[j] == '!':
                    j = j+1
                if j < n and pat[j] == ']':
                    j = j+1
                while j < n and pat[j] != ']':
                    j = j+1
                if j >= n:
                    res = res + '\\['
                else:
                    stuff = pat[i:j]
                    if '--' not in stuff:
                        stuff = stuff.replace('\\', r'\\')
                    else:
                        chunks = []
                        k = i+2 if pat[i] == '!' else i+1
                        while True:
                            k = pat.find('-', k, j)
                            if k < 0:
                                break
                            chunks.append(pat[i:k])
                            i = k+1
                            k = k+3
                        chunks.append(pat[i:j])
                        # Escape backslashes and hyphens for set difference (--).
                        # Hyphens that create ranges shouldn't be escaped.
                        stuff = '-'.join(s.replace('\\', r'\\').replace('-', r'\-')
                                         for s in chunks)
                    # Escape set operations (&&, ~~ and ||).
                    stuff = re.sub(r'([&~|])', r'\\\1', stuff)
                    i = j+1
                    if stuff[0] == '!':
                        stuff = '^' + stuff[1:]
                    elif stuff[0] in ('^', '['):
                        stuff = '\\' + stuff
                    res = '%s[%s]' % (res, stuff)
            else:
                res = res + re.escape(c)
        return r'(?s:%s)\Z' % res

    def validate_glob(self, value):
        if not value.endswith('$') and not value.endswith('*'):
            # Adding support for a prefix-based list of paths
            value = value + '**'
        return self.translate(value)

    def validate_closed_path(self, value):
        return f"{value}.*"

    def validate(self, value):
        if value.startswith('!'):
            is_negative = True
            value = value.lstrip('!')
        else:
            is_negative = False

        input_type = self.input_type(value)
        result = self.validate_according_to_type(input_type, value)
        if is_negative:
            return f"!{result}"
        return result

    def validate_according_to_type(self, input_type, value):
        if input_type == 'regex':
            try:
                re.compile(value)
                return value
            except re.error:
                raise SchemaError(f"{value} does not work as a regex")
        elif input_type == 'glob':
            return self.validate_glob(value)
        elif input_type == 'closed_path':
            return self.validate_closed_path(value)
        else:
            raise SchemaError(f"We did not detect what {value} is")


class CustomFixPath(object):
    # TODO (Thiago): Implement
    pass


class UserGivenBranchRegex(object):

    asterisk_to_regexp = re.compile(r'(?<!\.)\*')

    def validate(self, value):
        if value in ('*', '', None, '.*'):
            return '.*'
        else:
            # apple* => apple.*
            nv = self.asterisk_to_regexp.sub('.*', value.strip())
            if not nv.startswith(('.*', '^')):
                nv = '^%s' % nv
            if not nv.endswith(('.*', '$')):
                nv = '%s$' % nv
            re.compile(nv)
            return nv


class LayoutStructure(object):

    acceptable_objects = set([
        'changes',
        'diff',
        'file',
        'files',
        'flag',
        'flags',
        'footer',
        'header',
        'header',
        'reach',
        'suggestions',
        'sunburst',
        'tree',
        'uncovered'
    ])

    def validate(self, value):
        values = value.split(",")
        actual_values = [x.strip() for x in values]
        if not set(actual_values) <= self.acceptable_objects:
            extra_objects = set(actual_values) - self.acceptable_objects
            extra_objects = ','.join(extra_objects)
            raise SchemaError(f"Unexpected values on layout: {extra_objects}")
        return value


class BranchStructure(object):

    def validate(self, value):
        if not isinstance(value, str):
            raise SchemaError(f"Branch must be {str}, was {type(value)} ({value})")
        if value[:7] == 'origin/':
            return value[7:]
        elif value[:11] == 'refs/heads/':
            return value[11:]
        return value


class EncryptorWithAlreadyGeneratedKey(StandardEncryptor):

    def __init__(self, key):
        self.key = key
        self.bs = 16


class UserGivenSecret(object):
    encryptor = EncryptorWithAlreadyGeneratedKey(
        b']\xbb\x13\xf9}\xb3\xb7\x03)*0Kv\xb2\xcet'  # Same secret as in the main app
    )

    def validate(self, value):
        if value is not None and value.startswith('secret:'):
            self.decode(value)
        return value

    @classmethod
    def encode(cls, value):
        return 'secret:%s' % cls.encryptor.encode(value).decode()

    @classmethod
    def decode(cls, value):
        return cls.encryptor.decode(value[7:])


user_given_title = Regex(r'^[\w\-\.]+$')
flag_name = Regex(r'^[\w\.\-]{1,45}$')
percent_type = Percent()
branch_structure = BranchStructure()
branches_regexp = Regex(r'')
user_given_regex = UserGivenBranchRegex()
layout_structure = LayoutStructure()
path_structure = PathStructure()
base_structure = Or('parent', 'pr', 'auto')
branch = BranchStructure()
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
            Optional('range'): CoverageRange(),
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
        Optional('fixes'): Or(None, [CustomFixPath()]),
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
