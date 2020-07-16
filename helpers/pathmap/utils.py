def _extract_match(toc, index, seperator=","):
    """
    Extracts a path between seperators (,)

    :toc (str) Table of contents
    :index (int) Index of match

    returns full path from match
    """
    length = len(toc)
    start_index = index
    while toc[start_index] != seperator and start_index >= 0:
        start_index -= 1
    end_index = index
    while toc[end_index] != seperator and end_index < length - 1:
        end_index += 1
    if end_index == length - 1:
        end_index += 1
    match = toc[start_index + 1 : end_index].replace(seperator, "")
    return match
