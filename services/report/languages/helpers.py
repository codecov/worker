import types as ObjTypes
from json import JSONEncoder
from json import dumps
from collections import defaultdict
from itertools import chain, groupby

from app.helpers.sessions import Session
from covreports.utils.tuples import ReportLine, LineSession
from covreports.resources import ReportEncoder, Report
from covreports.utils import merge



END_OF_CHUNK = '\n<<<<< end_of_chunk >>>>>\n'

def combine_partials(partials):
    """
        [(INCLUSIVE, EXCLUSICE, HITS), ...]
        | . . . . . |
     in:    0+         (2, None, 0)
     in:  1   1        (1, 3, 1)
    out:  1 1 1 0 0
    out:  1   1 0+     (1, 3, 1), (4, None, 0)
    """
    # only 1 partial: return same
    if len(partials) == 1:
        return partials

    columns = defaultdict(list)
    # fill in the partials WITH end values: (_, X, _)
    [[columns[c].append(cov) for c in xrange(sc or 0, ec)]
     for (sc, ec, cov) in partials
     if ec is not None]

    # get the last column number (+1 for exclusiveness)
    lc = (max(columns.keys()) if columns else max([sc or 0 for (sc, ec, cov) in partials])) + 1
    # hits for (lc, None, eol)
    eol = []

    # fill in the partials WITHOUT end values: (_, None, _)
    [([columns[c].append(cov) for c in xrange(sc or 0, lc)], eol.append(cov))
     for (sc, ec, cov) in partials
     if ec is None]

    columns = [(c, merge.merge_all(cov)) for c, cov in columns.iteritems()]

    # sum all the line hits && sort and group lines based on hits
    columns = groupby(sorted(columns), lambda (c, h): h)

    results = []
    for cov, cols in columns:
        # unpack iter
        cols = list(cols)
        # sc from first column
        # ec from last (or +1 if singular)
        results.append([cols[0][0], (cols[-1] if cols else cols[0])[0] + 1, cov])

    # remove duds
    if results:
        fp = results[0]
        if fp[0] == 0 and fp[1] == 1:
            results.pop(0)
            if not results:
                return [[0, None, fp[2]]]

        # if there is eol data
        if eol:
            eol = merge.merge_all(eol)
            # if the last partial ec == lc && same hits
            lr = results[-1]
            if lr[1] == lc and lr[2] == eol:
                # then replace the last partial with no end
                results[-1] = [lr[0], None, eol]
            else:
                # else append a new eol partial
                results.append([lc, None, eol])

    return results or None


def list_to_dict(lines):
    """
    in:  [None, 1] || {"1": 1}
    out: {"1": 1}
    """
    if type(lines) is list:
        if len(lines) > 1:
            return dict([(ln, cov) for ln, cov in enumerate(lines[1:], start=1) if cov is not None])
        else:
            return {}
    else:
        return lines or {}

def _rstrip_none(lst):
    while lst[-1] is None:
        lst.pop(-1)
    return lst


def dumps_not_none(value):
    if isinstance(value, (list, ReportLine, LineSession)):
        return dumps(_rstrip_none(list(value)),
                     cls=ReportEncoder,
                     separators=(',', ':'))
    return value if value and value != 'null' else ''

def get_paths_from_flags(repository, flags):
    if flags:
        from covreports.helpers.yaml import walk
        return list(set(list(chain(*[(walk(repository, ('yaml', 'flags', flag, 'paths')) or [])
                                     for flag in flags]))))
    else:
        return []


class WithNone:
    def __enter__(self):
        pass

    def __exit__(self, *args):
        pass


def process_commit(commit, flags=None):
    if commit and commit['totals']:
        _commit = commit.pop('report', None) or {}
        _commit.setdefault('totals', commit.get('totals', None))
        _commit.setdefault('chunks', commit.pop('chunks', None))
        commit['report'] = Report(**_commit)
        if flags:
            commit['report'].filter(flags=flags)

    return commit
