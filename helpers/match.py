import re
from typing import List, Optional


def _convert_glob_to_regex(pattern: str) -> str:
    if pattern == "*":
        return ".*"
    return pattern


def match(patterns: Optional[List[str]], string: str) -> bool:
    if patterns is None or string in patterns:
        return True

    patterns = set(filter(None, patterns))
    negatives = set(filter(lambda a: a.startswith(("^!", "!")), patterns))
    positives = patterns - negatives

    # must not match
    for pattern in negatives:
        # matched a negative search
        regex_pattern = _convert_glob_to_regex(pattern.replace("!", ""))
        if re.match(regex_pattern, string):
            return False

    if positives:
        for pattern in positives:
            # match was found
            regex_pattern = _convert_glob_to_regex(pattern)
            if re.match(regex_pattern, string):
                return True

        # did not match any required paths
        return False

    else:
        # no positives: everyting else is ok
        return True
