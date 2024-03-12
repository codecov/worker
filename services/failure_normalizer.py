import regex

predefined_list_of_regexes_to_match = [
    r"[0-9a-fA-F]{8}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{12}",
]


class FailureNormalizer:
    """
    Class for normalizing a failure message

    Takes a list of strings to strings describing regexes that we want to match for
    and a boolean that toggles whether we should ignore the predefined
    list of patterns in the constructor

    The normalize_failure_message method on the class takes a string as a parameter
    it will remove all occurences of a match of the regexes specified in the list

    Usage:

    list_of_regex_strings = [
        r"(\d{4}-\d{2}-\d{2})",
    ]

    f = FailureNormalizer(list_of_regex_strings)
    s = '''
        abcdefAB-1234-1234-1234-abcdef123456 test_1 abcdefAB-1234-1234-1234-abcdef123456 test_2 2024-03-09
        test_3 abcdefAB-5678-5678-5678-abcdef123456 2024-03-10 test_4
        2024-03-10
        '''

    f.normalize_failure_message(s)

    will give:

    '''
     test_1 test_2
    test_3 test_4

    '''
    """

    def __init__(self, list_of_regex_strings, ignore_predefined=False):
        flags = regex.MULTILINE

        self.list_of_regex = []

        if not ignore_predefined:
            list_of_regex_strings += predefined_list_of_regexes_to_match

        for regex_string in list_of_regex_strings:
            compiled_regex = regex.compile(regex_string, flags=flags)
            self.list_of_regex.append(compiled_regex)

    def normalize_failure_message(self, failure_message):
        for compiled_regex in self.list_of_regex:
            for match_obj in compiled_regex.finditer(failure_message):
                actual_match = match_obj.group()
                failure_message = failure_message.replace(actual_match, "")
        return failure_message
