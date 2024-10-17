from typing import List, Optional

import regex
import sentry_sdk

from helpers.metrics import metrics

predefined_dict_of_regexes_to_match = {
    "UUID": [
        r"[0-9a-fA-F]{8}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{12}"
    ],
    "DATETIME": [
        r"(?:19|20)[0-9]{2}-(?:(?:0?[0-9])|(?:1[012]))-(?:(?:0?[0-9])|1[0-9]|2[0-9]|3[01])T(?:0[0-9]|1[0-9]|2[0-3]):(?:[0-5][0-9]):(?:[0-5][0-9])(?:Z|(?:-(?:0[0-9]:[03]0)))?",
        r"(?:19|20)[0-9]{2}(?:(?:0?[0-9])|(?:1[012]))(?:(?:0?[0-9])|1[0-9]|2[0-9]|3[01])T(?:0[0-9]|1[0-9]|2[0-3])(?:[0-5][0-9])(?:[0-5][0-9])(?:Z|(?:-(?:0[0-9]:[03]0)))?",
    ],
    "DATE": [
        r"(?:19|20)[0-9]{2}-(?:(?:0?[0-9])|(?:1[012]))-(?:(?:0?[0-9])\b|1[0-9]|2[0-9]|3[01])"
    ],
    "TIME": [
        r"(?:0[0-9]|1[0-9]|2[0-3]):(?:[0-5][0-9]):(?:[0-5][0-9])Z?",
        r"T(?:0[0-9]|1[0-9]|2[0-3])(?:[0-5][0-9])(?:[0-5][0-9])Z?",
    ],
    "URL": [
        r"[a-z]+:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
    ],
    "FILEPATH": [r"\/?[a-zA-Z0-9-_]+(\/[a-zA-Z0-9-_]+)+(?=\/([a-zA-Z0-9-_]+\/){2})"],
    "LINENO": [r":\d+:\d*"],
    "HEXNUMBER": [r"0?x[A-Fa-f0-9]+\b"],
    "HASH": [r"[0-9a-fA-F\-]{30}[0-9a-fA-F\-]*"],
    "NO": [r"[+-]?\d+(\.\d+)?\b"],
}


class FailureNormalizer:
    """
    Class for normalizing a failure message

    Takes a dict of strings to strings where the key is the replacement string and the value is
    the regex we want to match and replace occurences of and a boolean that toggles whether we
    should ignore the predefined list of patterns in the constructor

    The normalize_failure_message method on the class takes a string as a parameter
    it will replace all occurences of a match of the regexes specified in the list
    with the keys that map to that regex, in that string

    If the users

    Usage:

    dict_of_regex_strings = [
        "DATE": r"(\\d{4}-\\d{2}-\\d{2})",
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

    def __init__(
        self,
        user_dict_of_regex_strings: dict[str, list[str]],
        ignore_predefined=False,
        override_predefined=False,
        *,
        key_analysis_order: Optional[List[str]] = None,
    ):
        flags = regex.MULTILINE

        self.dict_of_regex = dict()
        self.key_analysis_order = key_analysis_order

        if not ignore_predefined:
            dict_of_list_of_regex_string = dict(predefined_dict_of_regexes_to_match)
            for key, user_regex_string in user_dict_of_regex_strings.items():
                if not override_predefined and key in dict_of_list_of_regex_string:
                    dict_of_list_of_regex_string[key] = (
                        user_regex_string + dict_of_list_of_regex_string[key]
                    )
                else:
                    dict_of_list_of_regex_string[key] = user_regex_string
        else:
            dict_of_list_of_regex_string = dict(user_dict_of_regex_strings)

        for key, list_of_regex_string in dict_of_list_of_regex_string.items():
            self.dict_of_regex[key] = [
                regex.compile(regex_string, flags=flags)
                for regex_string in list_of_regex_string
            ]

    @sentry_sdk.trace
    def normalize_failure_message(self, failure_message: str):
        with metrics.timer("failure_normalizer.normalize_failure_message"):
            key_ordering = self.key_analysis_order or self.dict_of_regex.keys()
            for key in key_ordering:
                list_of_compiled_regex = self.dict_of_regex[key]
                for compiled_regex in list_of_compiled_regex:
                    for match_obj in compiled_regex.finditer(failure_message):
                        actual_match = match_obj.group()
                        # Limit number of replaces to 1 so one match doesn't interfere
                        # With future matches
                        failure_message = failure_message.replace(actual_match, key, 1)
        return failure_message
