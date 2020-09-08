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
