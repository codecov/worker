import re


def regexp_match_one(regexp_patterns: list[re.Pattern], path: str) -> bool:
    for pattern in regexp_patterns:
        if pattern.match(path):
            return True
    return False
