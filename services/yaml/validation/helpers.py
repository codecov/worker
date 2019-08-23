import re

from schema import SchemaError
from covreports.encryption import StandardEncryptor


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
            return [float(split_value[0]), float(split_value[1])]
        except ValueError:
            raise SchemaError(f"{data} should have numbers as the range limits")


class Percent(object):

    def validate(self, value):
        if value.endswith('%'):
            value = value.replace('%', '')
        return float(value)


def determine_path_pattern_type(value):
    reserved_chars = ['*', '$', ']', '[']
    if not any(x in value for x in reserved_chars):
        return 'closed_path'
    if '**' in value or '/*' in value:
        return 'glob'
    if '.*' in value:
        return 'regex'
    return 'glob'


def translate(pat):
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


class PathStructure(object):

    path_with_star_but_not_dot_star = re.compile(r'(?<!\.)\*')

    def input_type(self, value):
        return determine_path_pattern_type(value)

    def validate_glob(self, value):
        if not value.endswith('$') and not value.endswith('*'):
            # Adding support for a prefix-based list of paths
            value = value + '**'
        return translate(value)

    def validate_closed_path(self, value):
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
        elif input_type == 'closed_path':
            return self.validate_closed_path(value)
        else:
            raise SchemaError(f"We did not detect what {value} is")


class CustomFixPath(object):

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
            return translate(value)
        elif input_type == 'closed_path':
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
            return self.decode(value)
        return value

    @classmethod
    def encode(cls, value):
        return 'secret:%s' % cls.encryptor.encode(value).decode()

    @classmethod
    def decode(cls, value):
        return cls.encryptor.decode(value[7:])
