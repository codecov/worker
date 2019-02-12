from copy import deepcopy
from math import floor, ceil
from yaml.parser import ParserError
from yaml.scanner import ScannerError

from helpers.config import config
from helpers.validators import validate_codecov_yml


def walk(_dict, keys, _else=None):
    try:
        for key in keys:
            if hasattr(_dict, '_asdict'):
                # namedtuples
                _dict = getattr(_dict, key)
            elif hasattr(_dict, '__getitem__'):
                _dict = _dict[key]
            else:
                _dict = getattr(_dict, key)
        return _dict
    except:
        return _else


def iformat(placeholder, argument, _else=''):
    if argument:
        return placeholder.format(argument)
    else:
        return _else


def yaml_join(org_yaml_json, repo_yaml=None, adapt=None):
    if org_yaml_json:
        default_n_org = merge(deepcopy(config.get(('site', ))), org_yaml_json)
    else:
        default_n_org = deepcopy(config.get(('site', )))

    if not repo_yaml:
        return default_n_org

    if type(repo_yaml) is dict:
        yml = merge(default_n_org, repo_yaml)
    else:
        try:
            yml = merge(default_n_org, validate_codecov_yml(repo_yaml, adapt=adapt))
        except (ScannerError, ParserError):
            # TODO inform the user
            return default_n_org

    # setup default statuses
    statuses = walk(yml, ('coverage', 'status'))
    if statuses:
        for context, value in statuses.iteritems():
            if value is True:
                yml['coverage']['status'][context] = {'default': {}}

    return yml


def merge(d1, d2):
    if type(d1) is not dict or type(d2) is not dict:
        return d2
    d1.update(dict([(k, merge(d1.get(k, {}), v)) for k, v in d2.iteritems()]))
    return d1


def choose(repository, coverage, choices):
    coverage = float(coverage)
    _range = walk(repository.data['yaml'], ('coverage', 'range'), config.get(('site', ))['coverage']['range'])
    low = float(_range[0])
    high = float(_range[1])

    if coverage >= high:
        return choices[-1]

    elif coverage <= low:
        return choices[0]

    i = (coverage - low) / (high - low)
    i = int(ceil(float(len(choices)) * i))
    return choices[i - 1]


def format(yml, value,
           strip=False,
           zero=None,
           null=None,
           plus=False,
           style='{0}'):
    if value is None:
        return null
    precision = int(walk(yml, ('coverage', 'precision'), 2))
    rounding = walk(yml, ('coverage', 'round'), 'nearest')
    value = float(value)
    if rounding == 'up':
        _ = float(pow(10, precision))
        c = (ceil(value * _) / _)
    elif rounding == 'down':
        _ = float(pow(10, precision))
        c = (floor(value * _) / _)
    else:
        c = round(value, precision)

    if zero and c == 0:
        return zero

    else:
        res = ('%%.%sf' % precision) % c

        if c == 0 and value != 0:
            # <.01
            return style.format('%s<%s' % (('+' if plus and value > 0 else '' if value > 0 else '-'),
                                (('%%.%sf' % precision) % (1.0 / float(pow(10, precision)))).replace('0.', '.')))

        if plus and res[0] != '-':
            res = '+' + res

        if strip and '.' in res:
            return style.format(res.rstrip('0').rstrip('.'))

        else:
            return style.format(res)
