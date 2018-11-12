import os
import certifi
import valideer as V
from yaml import load as yaml_load
from tornwrap import validators as _inherited_validators

from app import validators

home = os.getenv('CODECOV_HOME', os.getcwd())

enterprise = False

_yaml_config_validation = V.parse({
    '+setup': {
        'version': 'string',
        'debug': 'bool',  # production only
        'enterprise_license': V.Pattern('.{20,}'),
        'codecov_url': '?url',
        'webhook_url': '?url',
        'guest_access': '?bool',
        'encryption_secret': 'string',
        'logging': {
            'debug': 'bool',
            'datefmt': 'string'
        },
        'media': {
            'assets': '?string',
            'dependancies': '?string'
        },
        'slack_team_url': 'url',
        'http': {
            '+cookie_secret': '?string',
            'cookie_domain': 'string',
            'expire_user_cookies_days': '?int',  # default 365
            'force_https': 'bool',
            'use_etags': 'bool',
            'max_buffer_size': 'int',
            'gzip': 'bool',
            'content_security_policy': 'string',
            'timeouts': {
                'connect': 'int',
                'receive': 'int'
            }
        },
        'tasks': {
            'celery': {
                'default_queue': 'string',
                'prefetch': 'int',
                'soft_timelimit': 'int',
                'hard_timelimit': 'int',
                'acks_late': 'bool'
            },
            'upload': {
                'priority': 'int',  # default 3
                'max_retries': 'int',
                'countdown': 'int',
                'queue': 'string'
            },
            'notify': {
                'priority': 'int',  # default 2
                'max_retries': 'int',
                'countdown': 'int',
                'queue': 'string'
            },
            'yaml': {
                'priority': 'int',  # default 6
                'queue': 'string'
            },
            'pulls': {
                'priority': 'int',  # default 9
                'queue': 'string'
            },
            'status': {
                'priority': 'int',  # default 4
                'queue': 'string'
            },
            'refresh': {
                'priority': 'int',  # default 0
                'queue': 'string'
            },
            'synchronize': {
                'priority': 'int',  # default 0
                'queue': 'string'
            }
        },
        'cache': {
            'yaml': '?int',  # seconds to keep yaml in redis [default 600s/10m]
            'chunks': '?int',  # seconds to keep archived reports in redis [default 180/3m]
            'uploads': '?int',  # seconds to keep uploaded reports in redis [default 86400s/1d]
            'diff': '?int',  # seconds to cache the diff report in redis cache [default 600s/10m]
            'tree': '?int'  # seconds to cache the tree report in redis cache [default 600s/10m]
        }
    },
    'site': validators._codecov_yml,
    '+services': {
        'celery_broker': '?string',
        '+database_url': V.Pattern(r'^postgres://.*'),
        '+redis_url': V.Pattern(r'^redis://.*'),
        'google_analytics_key': '?string',
        'stripe': {  # production only
            'api_key': 'string',
            'publishable_key': 'string',
        },
        'slack': {
            'room_url': 'url',  # production only
            'team_url': 'url'
        },
        'sentry': {
            'server_dsn': 'string'
        },
        'statsd': {
            'periodic_callback_ms': 'int'
        },
        'gravatar': 'bool',
        'avatars.io': 'bool',
        'logentries': '?uuid',
        'ci_providers': V.Nullable(V.AnyOf('string', V.HomogeneousSequence('string'))),
        'notifications': {
            'slack': V.AnyOf('bool', validators.list_of('string')),
            'gitter': V.AnyOf('bool', validators.list_of('string')),
            'email': V.AnyOf('bool', validators.list_of('string')),
            'webhook': V.AnyOf('bool', validators.list_of('string')),
            'irc': V.AnyOf('bool', validators.list_of('string')),
            'hipchat': V.AnyOf('bool', validators.list_of('string'))
        },
        'rabbitmq_url': V.Nullable(V.Pattern(r'^amqp://.*')),
        'minio': {
            'dsn': 'url',
            'access_key_id': 'string',
            'secret_access_key': 'string',
            'bucket': 'string',
            'region': 'string',
            'verify_ssl': 'bool',
            'ttl': 'int',
            'client_uploads': 'bool',  # bash directly to minio
            'hash_key': 'string',
            'expire_raw_after_n_days': V.Nullable(V.AnyOf('int', 'bool')),
            'periodic_callback_ms': V.Nullable(V.AnyOf('int', 'bool'))
        }
    },
    'bitbucket': {
        'client_id': '?string',
        'client_secret': '?string',
        'access_token': '?string',  # DEPRECIATED
        'bot': {
            '+key': 'string',
            'secret': 'string',
            'username': 'string'
        },
        'organizations': validators.list_of('string'),
        'global_upload_token': '?string'
    },
    'bitbucket_server': {
        'url': '?url',
        'client_id': '?string',
        'organizations': validators.list_of('string'),
        'global_upload_token': '?string',
        'bot': {
            '+key': 'string',
            'secret': 'string',
            'username': 'string'
        },
        'verify_ssl': '?bool',
        'ssl_pem': '?file'
    },
    'github': {
        'client_id': '?string',
        'client_secret': '?string',
        'webhook_secret': 'string',
        'bot': {
            '+key': 'string',
            'secret': 'string',
            'username': 'string'
        },
        'integration': {
            '+id': 'int',
            '+pem': 'file',
            'expires': 'int'  # default 500
        },
        'organizations': validators.list_of('string'),
        'global_upload_token': '?string'
    },
    'github_enterprise': {
        'url': '?url',
        'client_id': '?string',
        'client_secret': '?string',
        'webhook_secret': 'string',
        'bot': {
            '+key': 'string',
            'secret': 'string',
            'username': 'string'
        },
        'integration': {
            '+id': 'int',
            '+pem': 'file',
            'expires': 'int'  # default 500
        },
        'organizations': validators.list_of('string'),
        'global_upload_token': '?string',
        'api_url': '?url',
        'verify_ssl': '?bool',
        'ssl_pem': '?file'
    },
    'gitlab': {
        'client_id': '?string',
        'client_secret': '?string',
        'bot': {
            '+key': 'string',
            'secret': 'string',
            'username': 'string'
        },
        'organizations': validators.list_of('string'),
        'global_upload_token': '?string',
    },
    'gitlab_enterprise': {
        'url': '?url',
        'client_id': '?string',
        'client_secret': '?string',
        'bot': {
            '+key': 'string',
            'secret': 'string',
            'username': 'string'
        },
        'organizations': validators.list_of('string'),
        'global_upload_token': '?string',
        'verify_ssl': '?bool',
        'ssl_pem': '?file',
    }
}, additional_properties=True).validate


def get(keys, _else=None):
    global configuration
    return _get(configuration, keys, _else)


def _get(obj, keys, _else=None):
    try:
        _next = obj
        for key in keys:
            _next = _next[key]
        return _next
    except Exception:
        return _else


def set(keys, value):
    global configuration
    _ = configuration
    for k in keys[:-1]:
        _ = _.setdefault(k, {})
    _[keys[-1]] = value


def pop(keys):
    global configuration
    return _pop(configuration, keys)


def _pop(dct, keys):
    _ = dct
    for k in keys[:-1]:
        _ = _.get(k, {})
    return _.pop(keys[-1], None)


def setdefault(keys, value, overnull=False):
    global configuration
    return _setdefault(configuration, keys, value, overnull)


def _setdefault(obj, keys, value, overnull=False):
    if value != '':
        _ = obj
        for k in keys[:-1]:
            _ = _.setdefault(k, {})

        if overnull and _.get(keys[-1]) is None:
            _[keys[-1]] = value
            return value
        else:
            return _.setdefault(keys[-1], value)


def initialize(configuration):
    global enterprise

    # add env with KEY__KEY or KEY.KEY
    for key, value in os.environ.iteritems():
        if '__' in key:
            _setdefault(configuration, key.lower().split('__'), value)
        elif '.' in key:
            _setdefault(configuration, key.lower().split('.'), value)

    # Find SSL Pem file
    if os.path.exists('/config/cacert.pem'):
        os.environ['REQUESTS_CA_BUNDLE'] = '/config/cacert.pem'
        os.environ['CACERT_PATH'] = '/config/cacert.pem'
    else:
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

    # steup redis database
    _setdefault(
        configuration,
        ('services', 'redis_url'),
        (
            os.getenv('REDIS_URL') or
            'redis://redis:@{}:{}'.format(
                os.getenv('REDIS_PORT_6379_TCP_ADDR', 'redis'),
                os.getenv('REDIS_PORT_6379_TCP_PORT', '6379')
            )
        )
    )

    # minio defaults -- docker compose
    for key, value in {
        'dsn': get(('setup', 'codecov_url')),
        'access_key_id': 'codecov-default-key',
        'secret_access_key': 'codecov-default-secret',
        'bucket': 'archive',
        'verify_ssl': False,
        'client_uploads': True,
        'hash_key': 'codecov-default-hashkey'
    }.iteritems():
        _setdefault(configuration, ('services', 'minio', key), value)

    _setdefault(
        configuration,
        ('services', 'celery_broker'),
        get(('services', 'redis_url'))
    )

    # steup postgres database
    _setdefault(
        configuration,
        ('services', 'database_url'),
        (
            os.getenv('DATABASE_URL') or
            'postgres://postgres:@{}:{}/postgres'.format(
                os.getenv('POSTGRES_PORT_5432_TCP_ADDR', 'postgres'),
                os.getenv('POSTGRES_PORT_5432_TCP_PORT', '5432')
            )
         )
    )

    # setup ssl mode for providers
    for key in configuration.keys():
        if key not in ('setup', 'services', 'site'):
            pempath = '/config/{0}.pem'.format(key)
            if os.path.exists(pempath):
                with open(pempath, 'r') as p:
                    if p.read() != '':
                        # pem found
                        _setdefault(configuration, (key, 'ssl_pem'), pempath)

    if isinstance(get(('services', 'ci')),  str):
        configuration['services']['ci'] = configuration['services']['ci'].split('\n')

    # moving depreciated settings
    for key, dest in (('setup.expire_user_cookies_days', 'setup.http.expire_user_cookies_days'),
                      ('setup.force_https', 'setup.http.force_https'),
                      ('setup.cookie_secret', 'setup.http.cookie_secret'),
                      ('setup.use_etags', 'setup.http.use_etags'),
                      ('setup.gzip', 'setup.http.gzip'),
                      ('setup.http_timeouts', 'setup.http.timeouts')):
        if _get(configuration, key.split('.')):
            _setdefault(configuration,
                        dest.split('.'),
                        _pop(configuration, key.split('.')))

    # more yaml defaults
    _setdefault(configuration, ('setup', 'codecov_url'), 'http://codecov', True)
    _setdefault(configuration, ('site', 'codecov', 'require_ci_to_pass'), True)
    _setdefault(configuration, ('site', 'coverage', 'precision'), 2)
    _setdefault(configuration, ('site', 'coverage', 'round'), 'down')
    _setdefault(configuration, ('site', 'coverage', 'range'), [70, 100])
    _setdefault(configuration, ('site', 'coverage', 'status', 'project'), True)
    _setdefault(configuration, ('site', 'coverage', 'status', 'patch'), True)
    _setdefault(configuration, ('site', 'coverage', 'status', 'changes'), False)
    _setdefault(configuration, ('site', 'comment', 'layout'), 'reach,diff,flags,tree,reach')
    _setdefault(configuration, ('site', 'comment', 'behavior'), 'default')
    _setdefault(configuration, ('setup', 'cache', 'yaml'), 600)
    _setdefault(configuration, ('setup', 'cache', 'chunks'), 300)
    _setdefault(configuration, ('setup', 'cache', 'uploads'), 86400)
    _setdefault(configuration, ('setup', 'cache', 'diff'), 300)
    _setdefault(configuration, ('setup', 'cache', 'tree'), 600)

    configuration = _yaml_config_validation(configuration)

    enterprise = bool(get(('setup', 'enterprise_license')))

    # torngit env
    os.environ['USER_AGENT'] = 'Codecov'
    for service, keys in (('github_enterprise', ('url', 'api_url')),
                          ('gitlab_enterprise', ('url', 'api_url')),
                          ('bitbucket_server', ('url', ))):
        if configuration.get(service):
            os.environ.update(dict([(('%s_%s' % (service, key)).upper(), configuration[service][key])
                                    for key in keys
                                    if configuration[service].get(key)]))


def get_verify_ssl(service):
    verify = get((service, 'verify_ssl'))
    if verify is False:
        return False
    return get((service, 'ssl_pem')) or os.getenv('REQUESTS_CA_BUNDLE')


def load_config():
    configuration = {}
    yaml_path = os.getenv('CODECOV_YML', '/config/codecov.yml')
    if os.path.exists(yaml_path):
        with open(yaml_path, 'r') as c:
            configuration = yaml_load(c.read())
    initialize(configuration)
    return configuration


# the global settings object
configuration = load_config()
