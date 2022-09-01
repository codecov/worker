def remove_non_ascii(string, replace_with=""):
    # ASCII control characters <=31, 127
    # Extended ASCII characters: >=128
    return "".join([i if 31 < ord(i) < 127 else replace_with for i in string])
