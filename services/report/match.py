import re


def match(patterns, string):
    if patterns is None or string in patterns:
        return True

    patterns = set(filter(None, patterns))
    negatives = filter(lambda a: a.startswith(('^!', '!')), patterns)
    positives = patterns - set(negatives)

    # must not match
    for pattern in negatives:
        # matched a negative search
        if re.match(pattern.replace('!', ''), string):
            return False

    if positives:
        for pattern in positives:
            # match was found
            if re.match(pattern, string):
                return True

        # did not match any required paths
        return False

    else:
        # no positives: everyting else is ok
        return True


def match_any(patterns, match_any_of_these):
    if match_any_of_these:
        for string in match_any_of_these:
            if match(patterns, string):
                return True
    return False


def regexp_match_one(regexp_patterns, path):
    for pattern in regexp_patterns:
        if pattern.match(path):
            return True
    return False


def patterns_to_func(patterns, assume=True):
    if not patterns:
        # No patterns provided, so return the assumption
        return (lambda p: assume)

    includes = set(filter(lambda p: not p.startswith('!'), patterns))
    excludes = set(patterns) - includes

    # create lists of pass/fails
    if '.*' in patterns:
        # match everything, just make sure it is not negative
        include_all = True
        includes = None
    elif assume and len(includes) == 0:
        include_all = True
    else:
        include_all = False
        includes = list(map(re.compile, includes))

    if '!.*' in patterns:
        exclude_all = False
        excludes = None
    elif not include_all and assume is False and len(excludes) == 0:
        exclude_all = True
    else:
        exclude_all = False
        excludes = list(map(lambda p: re.compile(p[1:]),
                       filter(lambda p: p.startswith('!'),
                              patterns)))

    def _match(value):
        if value:
            if include_all:
                # everything is included
                if excludes:
                    # make sure it is not excluded
                    return not regexp_match_one(excludes, value)
                else:
                    return True
            # we have to match once
            if regexp_match_one(includes, value) is True:
                # make sure it's not excluded
                if excludes and regexp_match_one(excludes, value):
                    return False
                else:
                    return True
            return False

        return False

    return _match
