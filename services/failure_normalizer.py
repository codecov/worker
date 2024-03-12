import regex

predefined_dict_of_regexes_to_match = {
    "UUID": r"[0-9a-fA-F]{8}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{12}",
    "DATETIME": r"(?:19|20)[0-9]{2}-(?:(?:0?[0-9])|(?:1[012]))-(?:(?:0?[0-9])|1[0-9]|2[0-9]|3[01])T(?:0[0-9]|1[0-9]|2[0-3]):(?:[0-5][0-9]):(?:[0-5][0-9])(?:Z|(?:-(?:0[0-9]:[03]0)))?",
    "DATETIME2": r"(?:19|20)[0-9]{2}(?:(?:0?[0-9])|(?:1[012]))(?:(?:0?[0-9])|1[0-9]|2[0-9]|3[01])T(?:0[0-9]|1[0-9]|2[0-3])(?:[0-5][0-9])(?:[0-5][0-9])(?:Z|(?:-(?:0[0-9]:[03]0)))?",
    "DATE": r"(?:19|20)[0-9]{2}-(?:(?:0?[0-9])|(?:1[012]))-(?:(?:0?[0-9])\b|1[0-9]|2[0-9]|3[01])",
    "TIME": r"(?:0[0-9]|1[0-9]|2[0-3]):(?:[0-5][0-9]):(?:[0-5][0-9])Z?",
    "TIME2": r"T(?:0[0-9]|1[0-9]|2[0-3])(?:[0-5][0-9])(?:[0-5][0-9])Z?",
    "URL": r"(?:(?:http)s?:\/\/)?\w+(?:\.\w+)+(?:(?:(?:\/*[\w\-]+\/)+(?:[\w\.]+)(:\d+:\d+)*))?",
}


class FailureNormalizer:
    """
    Class for normalizing a failure message

    Takes a dict of strings to strings where the key is the replacement string and the value is
    the regex we want to match and replace occurences of and a boolean that toggles whether we
    should ignore the predefined list of patterns in the constructor

    The normalize_failure_message method on the class takes a string as a parameter
    it will remove all occurences of a match of the regexes specified in the list

    If the users

    Usage:

    dict_of_regex_strings = [
        "DATE": r"(\d{4}-\d{2}-\d{2})",
    ]

    f = FailureNormalizer(dict_of_regex_strings)
    s = '''
        abcdefAB-1234-1234-1234-abcdef123456 test_1 abcdefAB-1234-1234-1234-abcdef123456 test_2 2024-03-09
        test_3 abcdefAB-5678-5678-5678-abcdef123456 2024-03-10 test_4
        2024-03-10
        '''

    f.normalize_failure_message(s)

    will give:

    '''
    UUID test_1 UUID test_2 DATE
    test_3 UUID DATE test_4
    DATE
    '''
    """

    def __init__(self, user_dict_of_regex_strings, ignore_predefined=False):
        flags = regex.MULTILINE

        self.dict_of_regex = dict()

        dict_of_regex_strings = user_dict_of_regex_strings
        if not ignore_predefined:
            dict_of_regex_strings = (
                predefined_dict_of_regexes_to_match | dict_of_regex_strings
            )

        for key, regex_string in dict_of_regex_strings.items():
            compiled_regex = regex.compile(regex_string, flags=flags)
            self.dict_of_regex[key] = compiled_regex

    def normalize_failure_message(self, failure_message):
        for key, compiled_regex in self.dict_of_regex.items():
            for match_obj in compiled_regex.finditer(failure_message):
                actual_match = match_obj.group()
                failure_message = failure_message.replace(actual_match, key)
        return failure_message
