import re

from schema import SchemaError
from covreports.encryption import EncryptorWithAlreadyGeneratedKey


class CoverageRangeSchemaField(object):

    """
        Pattern for the user to input a range like 60..90 (which means from 60 to 90)

        We accept ".." and "..." as separators

        This value is converted into a two members array

        CoverageRangeSchemaField().validate('30...99') == [30.0, 99.0]
    """

    def validate_bounds(self, lower_bound, upper_bound):
        if not 0 <= lower_bound <= 100:
            raise SchemaError(f"Lower bound {lower_bound} should be between 0 and 100")
        if not 0 <= upper_bound <= 100:
            raise SchemaError(f"Upper bound {upper_bound} should be between 0 and 100")
        if lower_bound > upper_bound:
            raise SchemaError(f"Upper bound {upper_bound} should be bigger than {lower_bound}")
        return [lower_bound, upper_bound]

    def validate(self, data):
        if isinstance(data, list):
            if len(data) != 2:
                raise SchemaError(f"{data} should have only two elements")
            try:
                lower_bound, upper_bound = sorted(float(el) for el in data)
                return self.validate_bounds(lower_bound, upper_bound)
            except ValueError:
                raise SchemaError(f"{data} should have numbers as the range limits")
        if '....' in data:
            raise SchemaError(f"{data} should have two or three dots, not four")
        elif '...' in data:
            splitter = '...'
        elif '..' in data:
            splitter = '..'
        else:
            raise SchemaError(f"{data} does not have the correct format")
        split_value = data.split(splitter)
        if len(split_value) != 2:
            raise SchemaError(f"{data} should have only two numbers")
        try:
            lower_bound = float(split_value[0])
            upper_bound = float(split_value[1])
            return self.validate_bounds(lower_bound, upper_bound)
        except ValueError:
            raise SchemaError(f"{data} should have numbers as the range limits")


class PercentSchemaField(object):
    """
        A field for percentages. Accepts both with and without % symbol.
        The end result is the percentage number

        PercentSchemaField().validate('60%') == 60.0
    """
    field_regex = re.compile(r'(\d+)(\.\d+)?%?')

    def validate(self, value):
        if not self.field_regex.match(value):
            raise SchemaError(f"{value} should be a number")
        if value.endswith('%'):
            value = value.rstrip('%')
        try:
            return float(value)
        except ValueError:
            raise SchemaError(f"{value} should be a number")


def determine_path_pattern_type(filepath_pattern):
    """
        Tries to determine whether `filepath_pattern` is a:
            - 'path_prefix'
            - 'glob'
            - 'regex'

        As you can see in the documentation for PathPatternSchemaField,
            the same pattern can be used as more than one way.

    Args:
        filepath_pattern (str): the filepath

    Returns:
        str: The probable type of that inputted pattern
    """
    reserved_chars = ['*', '$', ']', '[']
    if not any(x in filepath_pattern for x in reserved_chars):
        return 'path_prefix'
    if '**' in filepath_pattern or '/*' in filepath_pattern:
        return 'glob'
    expected_regex_star_cases = [']*', '.*']
    if '*' in filepath_pattern and not any(x in filepath_pattern for x in expected_regex_star_cases):
        return 'glob'
    try:
        re.compile(filepath_pattern)
        return 'regex'
    except re.error:
        return 'glob'


def translate_glob_to_regex(pat, end_of_string=True):
    """
        Translate a shell PATTERN to a regular expression.

        There is no way to quote meta-characters.

        This is copied from fnmatch.translate_glob_to_regex. If you could be
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
    if end_of_string:
        return r'(?s:%s)\Z' % res
    return r'(?s:%s)' % res


class PathPatternSchemaField(object):
    """This class holds the logic for validating and processing a user given path pattern

    This is how it works. The intention is to allow the user to give a string as an input,
        and in return, that string is used as a pattern to identify which paths to include/exclude
        from their report

    For that, we take the user input, and transform it into a regex that python can process

    The user can input three types of patterns:

        - path_prefix - It's when user inputs something like `path/to/folder`.
            That means that, every filename for a file that lives inside `path/to/folder`
                will match that pattern, regardless of how deep it is.
        - regex - The user inputs a regex directly. In this case we simply apply the regex to the
            filepath to see if it matches
        - glob - The user inputs a glob (as the glob that we use in unix, using `*` and `**`)

    This class tries to determinw which type of pattern the user inputted. We say "try", because
        some paths can be more than one type, and we try our best to see what the user meant.

    For example, `a.*` could match `a/folder1/path/file.py` as a regex, but not as a glob.
        As a glob, `a.*` could match a.yaml, a.py and a.cpp

    After determined the type, the code converts that type of pattern to a regex (in case
        the user inputted a regex, it is used as it is)

    One additional processing we do is to account for the usage of `!` by the user.
        `!` means negation, and although we support `ignore` fields, sometimes the users
        prefer to just use `!` to denote something they want to exclude.

    To see some examples of results from this validator field, take a look at
        services/yaml/tests/test_validation.py::TestPathPatternSchemaField
    """

    def input_type(self, value):
        return determine_path_pattern_type(value)

    def validate_glob(self, value):
        if not value.endswith('$') and not value.endswith('*'):
            # Adding support for a prefix-based list of paths
            value = value + '**'
        return translate_glob_to_regex(value)

    def validate_path_prefix(self, value):
        return f"^{value}.*"

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
        elif input_type == 'path_prefix':
            return self.validate_path_prefix(value)
        else:
            raise SchemaError(f"We did not detect what {value} is")


class CustomFixPathSchemaField(object):

    def input_type(self, value):
        return determine_path_pattern_type(value)

    def validate(self, value):
        if '::' not in value:
            raise SchemaError("Pathfix must split before and after with a ::")
        before, after = value.split("::", 1)
        if before == '' or after == '':
            return value
        before_input_type = self.input_type(before)
        before = self.validate_according_to_type(before_input_type, before)
        return f"{before}::{after}"

    def validate_according_to_type(self, input_type, value):
        if input_type == 'regex':
            try:
                re.compile(value)
                return value
            except re.error:
                raise SchemaError(f"{value} does not work as a regex")
        elif input_type == 'glob':
            return translate_glob_to_regex(value, end_of_string=False)
        elif input_type == 'path_prefix':
            return f"^{value}"
        else:
            raise SchemaError(f"We did not detect what {value} is")


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


class BranchSchemaField(object):

    def validate(self, value):
        if not isinstance(value, str):
            raise SchemaError(f"Branch must be {str}, was {type(value)} ({value})")
        if value[:7] == 'origin/':
            return value[7:]
        elif value[:11] == 'refs/heads/':
            return value[11:]
        return value


class UserGivenSecret(object):
    encryptor = EncryptorWithAlreadyGeneratedKey(
        b']\xbb\x13\xf9}\xb3\xb7\x03)*0Kv\xb2\xcet'  # Same secret as in the main app
    )

    def validate(self, value):
        if value is not None and value.startswith('secret:'):
            return self.decode(value)
        return value

    @classmethod
    def encode(cls, value):
        return 'secret:%s' % cls.encryptor.encode(value).decode()

    @classmethod
    def decode(cls, value):
        return cls.encryptor.decode(value[7:])
