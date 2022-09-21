import re
from typing import List, Optional


def match(patterns: Optional[List[str]], string: str) -> bool:
    if patterns is None or string in patterns:
        return True

    patterns = set(filter(None, patterns))
    negatives = set(filter(lambda a: a.startswith(("^!", "!")), patterns))
    positives = patterns - negatives

    # must not match
    for pattern in negatives:
        # matched a negative search
        if re.match(pattern.replace("!", ""), string):
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
