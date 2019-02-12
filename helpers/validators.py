import os
import re
import json
import valideer as V
from yaml import load
from colour import Color
from Crypto import Random
from pybars import Compiler
from datetime import datetime
from Crypto.Cipher import AES
from yaml.scanner import ScannerError
from base64 import b64decode, b64encode


home = os.getenv('CODECOV_HOME', os.getcwd())

handlebars = Compiler()

N = V.Nullable

_star_to_glob = re.compile(r'(?<!\.)\*').sub


class imagetoken(V.Pattern):
    name = 'image-token'
    regexp = re.compile(r"^\w{10}$")


class color(V.String):
    name = 'color'

    def validate(self, value, adapt=True):
        super(color, self).validate(value, adapt)
        return Color(value).hex


class list_of(V.HomogeneousSequence):
    name = 'list_of'

    def validate(self, value, adapt=True):
        if type(value) is not list:
            # takes the first value and makes a list
            value = [value]

        return super(list_of, self).validate(value, adapt)


class service(V.Enum):
    name = 'service'
    services = {'github': 'github', 'gh': 'github',
                'github-enterprise': 'github_enterprise', 'github_enterprise': 'github_enterprise', 'ghe': 'github_enterprise',
                'bitbucket': 'bitbucket', 'bb': 'bitbucket',
                'gitlab': 'gitlab', 'gl': 'gitlab',
                'bitbucket_server': 'bitbucket_server', 'bbs': 'bitbucket_server', 'stash': 'bitbucket_server',
                'gitlab-enterprise': 'gitlab_enterprise', 'gitlab_enterprise': 'gitlab_enterprise', 'gle': 'gitlab_enterprise'}

    def validate(self, value, adapt=True):
        res = self.services.get(value.lower())
        if res:
            return res
        self.error(value)

print(os.path.join(home, 'json/ci.json'))
with open(os.path.join(home, 'json/ci.json'), 'r') as f:
    ci = json.loads((f.read()))


class notify_message(V.Validator):
    name = 'notify_message'

    def validate(self, value, adapt=True):
        try:
            if type(value) is list:
                value = '\n'.join(value)
            handlebars.compile(str(value))(notification_example)

        except Exception as e:
            self.error(str(e))

        else:
            return value


class ci_provider(V.Validator):
    name = 'ci-provider'
    values = ci.keys()

    def validate(self, value, adapt=True):
        value = value.lower()
        if value == 'travis-org':
            value = 'travis'
        if value in self.values:
            return value
        self.error(value)


class percent(V.Pattern):
    name = 'percent'
    regexp = re.compile(r"^\d{1,45}(\.\d{1,25})?\%?$")

    def validate(self, value, adapt=True):
        super(percent, self).validate(str(value))
        if adapt:
            try:
                return float(value.replace('%', ''))
            except:
                return float(value)

        return value


class coverage(V.Validator):
    name = "coverage"
    validate = V.AnyOf("number", "string", V.Enum((True, None)),
                       V.HomogeneousSequence(V.HeterogeneousSequence("integer", "integer", "integer"))).validate


class custom_fixpath(V.Pattern):
    name = 'custom_fixpath'
    regexp = re.compile(r"^[^\:]*::[^\:]*$")

    def validate(self, value, adapt=True):
        # strip new lines & ending spaces
        if isinstance(value, str):
            nv = value.strip()
            super(custom_fixpath, self).validate(nv, adapt)
            # a/**/b => a/.*/b
            nv = nv.replace('**', '.*').lstrip('/')
            # a/*/b => a/[^\/]+/b
            nv = _star_to_glob(r'[^\/]+', nv)
            if adapt:
                if nv[0] not in '^:':
                    nv = '^' + nv
                return nv.strip()
            return value
        else:
            self.error(value)


BS = 16


def unpad(s):
    return s[:-ord(s[len(s)-1:])]


def pad(s):
    return s + (BS - len(s) % BS) * chr(BS - len(s) % BS)


class secret(V.Validator):
    name = 'secret'
    after_decode = None
    key = ']\xbb\x13\xf9}\xb3\xb7\x03)*0Kv\xb2\xcet'

    def __init__(self, after_decode):
        self.after_decode = V.parse(after_decode).validate

    def validate(self, value, adapt=True):
        if type(value) in str:
            if value[:7] == 'secret:':
                if adapt is True:  # used in /validate
                    return '<secret>'
                value = self.decode(value)
                if not value.startswith(adapt):
                    self.error('secret variable does not blong to this project')
                value = value.replace(adapt, '')

        return self.after_decode(value)

    @classmethod
    def encode(cls, value):
        iv = Random.new().read(AES.block_size)
        des = AES.new(cls.key, AES.MODE_CBC, iv)
        return 'secret:%s' % b64encode(iv + des.encrypt(pad(value)))

    @classmethod
    def decode(cls, value):
        value = b64decode(value[7:])
        iv = value[:16]
        cipher = AES.new(cls.key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(value[16:])).strip()


class regexp(V.String):
    name = 'regexp'
    asterisk_to_regexp = re.compile(r'(?<!\.)\*').sub

    def validate(self, value, adapt=True):
        super(regexp, self).validate(value, adapt)
        if value in ('*', '', None, '.*'):
            return '.*' if adapt else value
        else:
            # apple* => apple.*
            nv = self.asterisk_to_regexp('.*', value.strip())
            if not nv.startswith(('.*', '^')):
                nv = '^%s' % nv
            if not nv.endswith(('.*', '$')):
                nv = '%s$' % nv
            re.compile(nv)
            return nv if adapt else value


class glob(regexp):
    name = 'glob'

    def validate(self, value, adapt=True):
        """
        /folder =>    folder.*
        ./folder =>   folder.*
        folder/ =>    folder/.*
        !/folder/ =>  !folder/.*
        path/**/ =>   path/.*/.*
        """

        nv = value+''

        # */abc => .*/abc
        if nv.startswith('*/'):
            nv = '.*/' + nv[2:]

        nv = '^' + nv.strip()\
                     .replace('^!', '!')\
                     .replace('!^', '!')\
                     .lstrip('^/')\
                     .replace('/*/', '/**/')\
                     .replace('!/', '!')

        if nv.startswith('^./'):
            nv = '^'+nv[3:]
        # abc/* => abc/.*
        if nv.endswith('/*'):
            nv = nv[:-2] + '/.*'
        # a/**/b => a/.*/b
        nv = nv.replace('**', '.*')
        # a/*/b => a/[^\/]+/b
        nv = _star_to_glob(r'[^\/]+', nv)
        # add ending capture
        if not nv.endswith(('.*', '$', '[^\/]+')):
            nv = nv + '.*'

        # complete the regexp treatment
        nv = super(glob, self).validate(nv, adapt)

        if adapt:
            return nv

        return value


class coverage_range(V.Pattern):
    name = 'coverage_range'
    regexp = re.compile(r'^\d{1,3}(\.\d{1,5})?\.{2,3}\d{1,3}(\.\d{1,5})?$')

    def validate(self, value, adapt=True):
        if type(value) is list:
            assert len(value) == 2
            assert 0 <= float(value[0]) <= 100
            assert 0 <= float(value[1]) <= 100
            return map(float, value)

        super(coverage_range, self).validate(value, adapt)
        if '...' in value:
            return sorted(map(float, value.split('...')))
        else:
            return sorted(map(float, value.split('..')))


base = V.Enum(('parent', 'pr', 'auto'))
_title = V.Pattern(r'^[\w\-\.]+$')
_flags = list_of(V.Pattern(r'^[\w\.\-]{1,45}$'))
_branches = list_of('regexp')
_notification = {
    'url': N(secret('url')),
    'branches': N(_branches),
    'threshold': '?percent',
    'message': 'notify_message',
    'flags': N(_flags),
    'base': base,
    'only_pulls': 'bool',
    'paths': N(list_of('glob'))
}


def Dict(d1, d2=None, remove=None):
    d = d1.copy()
    d.update(d2 or {})
    map(d.pop, remove or [])
    return d


def notifications(*args):
    return V.Mapping(_title, Dict(_notification, *args))


class _layout(V.String):
    name = 'layout'
    _set = set((
        'header',
        'footer',
        'diff',
        'file', 'files',
        'flag', 'flags',
        'reach',
        'sunburst',
        'uncovered',
        'header', 'tree', 'changes', 'suggestions'  # depreciated
    ))

    def validate(self, value, adapt=True):
        super(_layout, self).validate(value, adapt)
        values = map(lambda a: a.strip(), filter(None, value.split(',')))
        if set(map(lambda v: v.split(':')[0], values)) <= self._set:
            return value
        self.error(value)

    @property
    def humanized_name(self):
        return 'must be a list with values: "reach, diff, flags, files" in any order'


class query_flags(V.Pattern):
    name = 'query_flags'
    regexp = re.compile(r'^([\w\.\-]{1,45})((\,|\s|\+)[\w\.\-]{1,45})*$')

    def validate(self, value, adapt=True):
        super(query_flags, self).validate(value, adapt)
        return list(set(re.split(', +', value)))


_status = {
    'branches': N(_branches),
    'if_no_uploads': V.Enum(('success', 'failure', 'error', 'ignore')),
    'if_not_found': V.Enum(('success', 'failure', 'error', 'ignore')),
    'if_ci_failed': V.Enum(('success', 'failure', 'error', 'ignore')),
    'skip_if_assumes': 'bool',  # [TODO] skip setting status if any assumptions are made (keeping in mind flags mentioned)
    'informational': 'bool',  # always set to "sucess" regardless of output
    'disable_approx': 'bool',
    'target': V.AnyOf(V.Enum(('auto', )), 'percent'),
    'threshold': '?percent',
    'only_pulls': 'bool',
    'include_changes': 'bool',
    'base': base,
    'measurement': N(V.Enum(('line', 'statement', 'branch', 'method', 'complexity'))),
    'flags': N(_flags),
    'paths': N(list_of('glob'))
}

_codecov_yml = {
    'codecov': {
        'url': 'url',
        'token': 'string',
        'slug': 'string',
        'bot': 'string',
        'branch': 'branch',
        'ci': ['string'],
        'assume_all_flags': 'bool',
        'strict_yaml_branch': 'string',  # only get the yaml from this branch
        'max_report_age': N(V.AnyOf('string', 'integer', 'bool')),
        'disable_default_path_fixes': 'bool',
        'require_ci_to_pass': 'bool',
        'allow_coverage_offsets': 'bool',
        'allow_pseudo_compare': 'bool',
        'archive': {
            'uploads': 'bool'  # disable archiving raw uploads
        },
        'notify': {
            'after_n_builds': 'integer',
            'countdown': 'integer',
            'delay': 'integer',
            'wait_for_ci': 'bool',
            'require_ci_to_pass': 'bool'  # [DEPRECIATED] moved to codecov.require_ci_to_pass
        },
        'ui': {
            'hide_density': V.AnyOf('bool', list_of('string')),
            'hide_complexity': V.AnyOf('bool', list_of('string')),
            'hide_contexual': 'bool',
            'hide_sunburst': 'bool',
            'hide_search': 'bool'
        }
    },
    'coverage': {
        'precision': V.Range('integer', min_value=0, max_value=5),
        'round': V.Enum(('down', 'up', 'nearest')),
        'range': 'coverage_range',
        'notify': {
            'irc': notifications({
                'channel': 'string',
                'password': secret('string'),
                'nickserv_password': secret('string'),
                'notice': 'bool'
            }),
            'slack': notifications({'attachments': 'layout'}),
            # 'flowdock': N(notifications()), [FUTURE]
            'gitter': notifications(),
            'hipchat': notifications({'card': 'bool',
                                      'notify': 'bool'}),
            'webhook': notifications(None, ['message']),
            'email': notifications({
                'layout': 'layout',
                '+to': list_of(secret('string'))
            }, ['url', 'message'])
        },
        'status': V.AnyOf('bool', {
            'project': V.AnyOf('bool',
                               V.Mapping(_title,
                                         N(V.AnyOf('bool', Dict(_status))))),
            'patch': V.AnyOf('bool',
                             V.Mapping(_title,
                                       N(V.AnyOf('bool', Dict(_status))))),
            'changes': V.AnyOf('bool',
                               V.Mapping(_title,
                                         N(V.AnyOf('bool', Dict(_status, None, ['target', 'include_changes', 'threshold'])))))
        })
    },
    'complexity': {

    },
    'ignore': N(list_of('glob')),
    'fixes': N(list_of('custom_fixpath')),
    'flags': V.Mapping(_title, {
        'joined': 'bool',            # include in master report
        'required': 'bool',          # if not provided fail statuses
        'ignore': N(list_of('glob')),   # [depreciated] which paths to ignore
        'paths': N(list_of('glob')),     # which paths to include or ignore
        'assume': V.AnyOf('bool', {
            'branches': N(_branches),  # all branches are assumed if not provided, otherwise: must match one of these branches
        })
    }),
    'parsers': {
        'javascript': {
            'enable_partials': 'bool'
        },
        'v1': {
            'include_full_missed_files': 'bool'  # [DEPRECIATED]
        },
        'gcov': {
            'branch_detection': {
                'conditional': 'bool',
                'loop': 'bool',
                'method': 'bool',
                'macro': 'bool'
            }
        }
    },
    'comment': V.AnyOf('bool', {
        'layout': N('layout'),
        'require_changes': 'boolean',
        'require_base': 'boolean',
        'require_head': 'boolean',
        'branches': N(_branches),
        'behavior': V.Enum(('default', 'once', 'new', 'spammy')),
        'flags': N(_flags),  # DEPRECIATED
        'paths': N(list_of('glob'))  # DEPRECIATED
    })
}


_validate_codecov_yml = V.parse(_codecov_yml, additional_properties=False).validate
# - !hotfix* => - "!hotfix*"
# - */hotfix/* => - "*/hotfix/*"
add_parenth = re.compile(r'^( *\- +)([^\"\'][^\s]+)', re.M)
# paths: !hotfix* => paths:"!hotfix*"
# paths: */hotfix/* => paths:"*/hotfix/*"
add_parenth_2 = re.compile(r'^(\s*\w+:\s+(\![^\n]+))', re.M)
# - ".*\.png" => - ".*\\.png"
escape_escaping = re.compile(r'(?<=[^\\])[\\](?=[^\\])', re.M)
# - branches: * => branches: "*"
catch_all = re.compile(r'(\:|\-)\s+\*\s*\n', re.M)


def validate_codecov_yml(yml, adapt=True):
    if type(yml) is not dict:
        # replace tabs with spaces
        yml = yml.replace('\t', '  ')
        yml = add_parenth.sub('\g<1>"\g<2>"', yml)
        yml = add_parenth_2.sub('\g<1>"\g<2>"', yml)
        yml = escape_escaping.sub('\\\\\\\\', yml)
        yml = catch_all.sub('\g<1> "*"\n', yml)
        try:
            yml = load(yml)
        except ScannerError as e:
            raise V.ValidationError(str(e))

    assert type(yml) is dict, "Invalid yaml value. Must be Mapping"

    # migrations
    coverage = yml.get('coverage', {})
    if 'flags' in coverage:
        yml['flags'] = coverage.pop('flags')
    if 'parsers' in coverage:
        yml['parsers'] = coverage.pop('parsers')
    if 'ignore' in coverage:
        yml['ignore'] = coverage.pop('ignore')
    if 'fixes' in coverage:
        yml['fixes'] = coverage.pop('fixes')

    try:
        yml['codecov']['require_ci_to_pass'] = yml['codecov']['notify'].pop('require_ci_to_pass')
    except:
        pass

    return _validate_codecov_yml(yml, adapt=adapt)


graphs = {
    'width': 'id',
    'height': 'id',
    'size': 'id',
    'border-size': 'id',
    'border-color': 'color',
    'token': 'image-token',
    'agg': V.Enum(('hour', 'day', 'week', 'month', 'commit')),
    'color': 'bool',
    'legend': 'bool',
    'hg': 'bool',
    'vg': 'bool',
    'flag': 'query_flags',
    'inc': V.Enum(('totals', )),
    'method': V.Enum(('avg', 'max', 'min')),
    'time': 'daterange',
    # https://github.com/codecov/support/issues/81
    'yaxis': 'coverage_range',
    'height': 'int',
    'width': 'int',
    'precision': V.Enum(('0', '1', '2')),
    'round': V.Enum(('up', 'down', 'nearest')),
    'limit': 'int',
    'order': V.Enum(('asc', 'desc'))
}

_pr = V.Nullable(V.Pattern(r"^(\d+|false|null|undefined|true)$"))
uuid = re.compile(r"^[0-9a-f]{8}(-?[0-9a-f]{4}){3}-?[0-9a-f]{12}$")

upload = {
    'owner': '?handler',
    'repo': '?handler',
    'slug': '?slug',
    'service': V.Nullable('ci-provider'),
    'branch': '?branch',
    '+commit': 'commit',
    'tag': 'string',
    'flags': N(V.Pattern(r'^[\w\,]+$')),
    'token': '?string',
    'build': '?string',
    'name': '?string',
    'package': 'string',
    'root': 'string',  # depreciated
    'build_url': V.Nullable(V.Pattern(r'^https?\:\/\/(.{,100})')),
    'job': '?string',
    'travis_job_id': '?id',  # depreciated by ?job
    'pr': _pr,
    'pull_request': _pr,  # depreciated by ?pr
    's3': '?int',
    'yaml': 'string',
    'url': 'url'  # custom location with the report is found
}


ratio = V.Pattern(r'^-?((\d{1,2}\.\d{5})|0|100)$')
formatted_ratio = V.Pattern(r'^\d{1,3}(\.\d{1,5})?$')
N = V.Nullable
_coverage = V.AnyOf('boolean', 'integer', V.Pattern(r'\d+/\d+'))
partial_coverage = V.HomogeneousSequence(V.HeterogeneousSequence(N('integer'), N('integer'), coverage))
_diff_type = V.Enum(('modified', 'deleted', 'new', 'ignored', 'empty', 'binary'))
date = V.AnyOf(V.Type(datetime), 'string', 'integer')
complexity = V.AnyOf('integer', V.HeterogeneousSequence('integer', 'integer'))


with open(os.path.join(home, 'src/json/languages.json'), 'r') as f:
    languages = json.loads((f.read()))


class HeterogeneousSequenceOptional(V.HeterogeneousSequence):
    """A validator that accepts heterogeneous, variable size sequences."""
    def validate(self, value, adapt=True):
        if len(value) != len(self._item_validators):
            value.extend([None] * (len(self._item_validators) - len(value)))
        return super(HeterogeneousSequenceOptional, self).validate(value)


line = {
    '+c': N(_coverage),
    's': V.HomogeneousSequence(HeterogeneousSequenceOptional('integer',
                                                             N(V.AnyOf('boolean', 'integer', V.Pattern(r'\d+/\d+'), partial_coverage)),
                                                             N(['string']),
                                                             N(partial_coverage),
                                                             N(complexity))),
    'p': partial_coverage,
    't': V.Enum(('b', 'm', 's')),
    'C': complexity
    # 'm': V.HomogeneousSequence(V.HomogeneousSequence('string', 'string'))
    #                            {
    #     # '+s': 'id',  # what session
    #     '+t': 'string',  # message title
    #     'm': 'string',  # message markdown content
    #     'e': 'string',  # message font-awesome icon
    #     'c': V.HeterogeneousSequence('integer', 'integer')  # [start column, end column]
    # })
}

log = V.Object(optional={
    'method': 'string',
    'pr': 'id',
    'obo': 'handler',
    'time': 'string'
}, required={
    'event': V.Enum(('comment', 'status', 'gitter', 'webhook', 'irc', 'slack', 'upload', 'queue'))
}, additional=True)

_change = {
    'p': 'string',  # path
    'm': _diff_type,  # type
    'l': V.Mapping('string', V.HeterogeneousSequence('?string', N(_coverage), N(_coverage))),
    'd': 'boolean',  # in diff
    'b': '?string',  # path before moved
    't': N(V.AnyOf('boolean', {  # totals
        'f': 'integer',
        'h': 'integer',
        'm': 'integer',
        'p': 'integer',
        'n': 'integer',
        'b': 'integer',
        'd': 'integer',
        'x': 'integer',
        'M': 'integer'
    }))
}

_changes = V.HomogeneousSequence(_change)

totals = {
    '+f': 'integer',
    '+h': 'integer',
    '+m': 'integer',
    '+p': 'integer',
    '+n': 'integer',
    '+b': 'integer',
    '+d': 'integer',
    '+M': 'integer',
    '+c': ratio,
    's': 'integer',
    'C': 'integer'
}

_report = {
    'files': V.Mapping('string', {
        'l': V.Mapping('id', N(line)),
        'eof': 'integer',
        't': {
            '+h': 'integer',
            '+m': 'integer',
            '+p': 'integer',
            '+n': 'integer',
            '+b': 'integer',
            '+d': 'integer',
            '+x': 'integer',
            '+M': 'integer',
            '+r': ratio,
            '+c': ratio
        }
    }),
    'changes': N(_changes),
    'parent': 'string',
    'sessions': V.Mapping('id', {
        'c': 'ci-provider',  # service name
        'n': 'string',  # build number
        'j': 'string',  # job number
        'd': 'integer',  # time
        'u': 'string',  # build url
        'f': V.HomogeneousSequence(V.Pattern(r'^\w+$')),  # flags
        'p': 'boolean',  # ci passed
        'e': V.Mapping('string', 'string'),  # env{}
        't': totals,  # totals{}
        'a': 'string'  # archive link to S3 archive
    }),
    'totals': totals
}

_diff = {
    'coverage': totals,
    '+files': V.Mapping('string', {
        'coverage': Dict(totals, None, ['+f']),
        '+type': _diff_type,
        'before': N('string'),
        '+segments': [{
            # [\d, \d|'', \d, \d|'',]
            # http://cl.ly/3T2J161F362N
            '+header': V.HeterogeneousSequence(*((V.Pattern(r'\d+'), ) * 4)),
            '+lines': [V.Pattern(r'^(\s|\+|\-).*')]
        }],
        'totals': {
            '+added': 'integer',
            '+removed': 'integer'
        }
    })
}

_owner = {
    '+service': 'service',
    '+username': 'string',
    '+service_id': 'string',
    'email': '?string',
    'guest': 'boolean',
    'updatestamp': N(date),
    'name': 'string',
    'cache': {
        'stats': {
            'users': 'integer',
            'repos': 'integer'
        }
    }
}

_author = {
    '+service': 'service',
    '+service_id': 'string',
    '+username': 'string',
    '+email': '?string',
    '+name': '?string'
}

_trend = {
    'type': V.Enum(('flag', 'file', 'folder')),
    'path': '?string',
    'flag': '?string',
    'totals': totals,
    'trending': V.Enum(('up', 'down', None)),
    'grade': V.Enum(('A', 'B', 'C', 'D', 'F'))
}

_repo = {
    '+name': 'string',
    '+service_id': 'string',
    'state': '?string',
    'image_token': 'string',
    '+branch': 'string',
    '+private': 'boolean',
    '+activated': 'boolean',
    'updatestamp': N(date),
    'authors': [],
    'language': N(V.Enum(languages.keys())),
    'repoid': 'int',
    'forkid': N('int'),
    'fork': {},
    'yaml': N(V.Type(dict)),
    'updatestamp': N(date),
    'branch': 'string',
    'upload_token': N('uuid'),
    'cache': {
        'commit': {
            'commitid': 'string',
            'timestamp': date,
            'author': _author,
            'totals': totals,
            'graph': 'string'
        },
        'yaml': 'string',  # file path to custom location of codecov.yml in repo
        'stats': {
            'trending': V.Enum(('up', 'down', None)),
            'users': 'integer',
            'repos': 'integer'
        },
        'trends': [_trend],
        'users': [{
            'ownerid': 'id',
            'username': 'string',
            'codebase': ratio,
            'coverage': ratio,
            'grade': V.Enum(('A', 'B', 'C', 'D', 'F'))
        }]
    }
}

_session = {
    '+sessionid': 'id',
    '+type': V.Enum(('api', 'login')),
    'useragent': '?string',
    'ip': '?string',
    'lastseen': N(date),
    'token': 'string',  # only when first created
    'name': '?string'
}

_pull = {
    '+pullid': 'int',
    'head': V.Type(dict),
    'base': V.Type(dict),
    'totals': {
        '+head': totals,
        '+base': N(totals),
        '+diff': N(totals)
    },
    'title': 'string',
    'timestamp': date,
    'author': _author,
    'number': 'int',
}

_commit = {
    'report': _report,
    'author': _author,
    'deleted': '?boolean',
    'state': V.Enum((None, 'pending', 'complete', 'error')),
    '+timestamp': N(date),
    'updatestamp': N(date),
    'parent': '?string',
    'merged': '?boolean',
    '+commitid': 'string',
    'branch': 'string',
    'notified': 'boolean',
    'ci_passed': '?boolean',
    '+message': 'string',
    'chunk': ['string'],
    'totals': totals,
    'parent_totals': N(totals),
    'changes': N(_changes),
    'logs': N([log]),
    'pullid': '?int',
    'tip': 'string'
}

api_schema = {
    'owner': _owner,
    'teams': [{
        '+username': 'string',
        '+repos': N([_repo]),
        '+updatestamp': N(date),
        '+name': 'string',
        '+service': 'service',
        '+service_id': 'string',
        '+ownerid': 'int'
    }],
    'flare': V.Type(list),
    'repo': _repo,
    'repos': [_repo],
    'diff': N(_diff),
    'session': _session,
    'sessions': [_session],
    'commit': N(_commit),
    'commits': [_commit],
    'pulls': V.HomogeneousSequence(_pull),
    'pull': _pull,
    'branches': [{
        '+branch': 'string',
        'commit': _commit,
        'is_contributor': 'boolean',
        'head': 'string',
        'authors': []
    }],
    'logs': [log],
    'customer': {
        '+stripe_customer_id': N(V.Pattern(r'^cus_')),
        '+stripe_subscription_id': N(V.Pattern(r'^sub_')),
        '+ownerid': 'int',
        'plan': '?string',
        'free': 'int',
        'invoice_details': '?string',
        'repos_activated': 'int',
        'yaml_bot': '?string',
        'bot': '?string',
        '+credits': 'int'
    },
    'invoices': V.Type(dict),
    'invoice': V.Type(dict),
    'base': N({
        'commitid': 'string',
        'branch': 'branch',
        'timestamp': V.AnyOf(V.Type(datetime), 'string'),
    }),
    'head': N({
        'commitid': 'string',
        'branch': 'branch',
        'timestamp': V.AnyOf(V.Type(datetime), 'string'),
    }),
    'source': 'string',
    'plans': V.Mapping('string', {
        'name': 'string',
        'repos': 'int',
        'price': 'int'
    }),
    'uncovered': N({
        'files': [{
            'content': 'string',
            'start': 'number',
            'file': 'string',
            'partial': 'number',
            'missed': 'number',
            'coverage': 'number',
            'end': 'number',
            'worth': 'number'
        }],
        'partial': 'number',
        'missed': 'number',
        'coverage': 'number'
    }),
    'references': {
        '+base': '?string',
        '+head': 'string'
    },
    'changes': N(_changes),
    'sources': N(V.Mapping('string', 'string')),
    'meta': {
        'status': V.Enum((200, 201, )),
        'page': 'int',
        'limit': 'int',
        'size': 'int'
    }
}

changes = V.parse(_changes).validate


error = V.parse({
    '+meta': {
        '+status': V.Enum((400, 401, 402, 404, 405, 406, 500))
    },
    '+error': {
        '+reason': 'string',
        'context': '?string'
    }
}).validate


notification_payload = V.parse({
    '+repo': {
        '+name': 'string',
        '+url': 'url',
        '+private': 'boolean',
        '+service_id': 'string'
    },
    '+owner': {
        '+service': 'service',
        '+service_id': 'string',
        '+username': 'string'
    },
    '+base': N(Dict(_commit, {'service_url': 'url', 'url': 'url'}, ['report'])),
    '+head': Dict(_commit, {'service_url': 'url', 'url': 'url'}, ['report']),
    '+pull': N({
        'base': {
            'commit': 'string',
            'branch': 'string'
        },
        'head': {
            'commit': 'string',
            'branch': 'string'
        },
    }),
    'compare': {
        'message': '?string',
        'url': '?url',
        'notation': V.Enum(('+', '-', '')),
        'coverage': N(formatted_ratio)
    }
}, additional_properties=False).validate

api = V.parse(api_schema, additional_properties=False).validate

diff = V.parse(_diff).validate

report = V.parse(_report, additional_properties=False).validate

# _pm = V.Pattern(r'^(\+|\-)\d+(\.\d{,5})?$')
# diff_totals = V.parse(dict([(k, _pm) for k in 'fhmpnbdxMrc']), additional_properties=False).validate
