def regexp_match_one(regexp_patterns, path) -> bool:
    for pattern in regexp_patterns:
        if pattern.match(path):
            return True
    return False
