from collections import defaultdict
from itertools import groupby

from covreports.utils import merge


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
    [
        [columns[c].append(cov) for c in range(sc or 0, ec)]
        for (sc, ec, cov) in partials
        if ec is not None
    ]

    # get the last column number (+1 for exclusiveness)
    lc = (
        max(columns.keys()) if columns else max([sc or 0 for (sc, ec, cov) in partials])
    ) + 1
    # hits for (lc, None, eol)
    eol = []

    # fill in the partials WITHOUT end values: (_, None, _)
    [
        ([columns[c].append(cov) for c in range(sc or 0, lc)], eol.append(cov))
        for (sc, ec, cov) in partials
        if ec is None
    ]

    columns = [(c, merge.merge_all(cov)) for c, cov in columns.items()]

    # sum all the line hits && sort and group lines based on hits
    columns = groupby(sorted(columns), lambda c: c[1])

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
            return dict(
                [
                    (ln, cov)
                    for ln, cov in enumerate(lines[1:], start=1)
                    if cov is not None
                ]
            )
        else:
            return {}
    else:
        return lines or {}


def remove_non_ascii(string, replace_with=""):
    # ASCII control characters <=31, 127
    # Extended ASCII characters: >=128
    return "".join([i if 31 < ord(i) < 127 else replace_with for i in string])
