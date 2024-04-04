from dataclasses import dataclass
from enum import Enum
from typing import List

import regex


class EscapeEnum(Enum):
    APPEND = "append"
    PREPEND = "prepend"
    REPLACE = "replace"


@dataclass
class Replacement:
    strings: List[str]
    output: str
    method: EscapeEnum


class StringEscaper:
    """
    Class to use to escape strings using format defined
    through a dict.

    Args:
        escape_def: list of Replacement that defines how to escape
        characters

        string is escaped by applying method in each Replacement
        to each char in Replacement.chars using the char in output

        for example:
            escape_def = [
                Replacement(["1"], "2", EscapeEnum.APPEND),
                Replacement(["3"], "4", EscapeEnum.PREPEND),
                Replacement(["5", "6"], "6", EscapeEnum.REPLACE),
            ]

            escaper = StringEscaper(escape_def)

            escaper.replace("123456")

            will give: "12243466"
    """

    def __init__(self, escape_def: List[Replacement]):
        self.escape_def = escape_def

    def replace(self, replacement_target):
        for replacement in self.escape_def:
            for string in replacement.strings:
                if replacement.method == EscapeEnum.PREPEND:
                    replacement_target = replacement_target.replace(
                        string, f"{replacement.output}{string}"
                    )
                elif replacement.method == EscapeEnum.APPEND:
                    replacement_target = replacement_target.replace(
                        string, f"{string}{replacement.output}"
                    )
                elif replacement.method == EscapeEnum.REPLACE:
                    replacement_target = replacement_target.replace(
                        string, replacement.output
                    )
        return replacement_target


MAX_PATH_COMPONENTS = 3


# matches file paths with an optional line number and column at the end:
# /Users/josephsawaya/dev/test-result-action/demo/calculator/calculator.test.ts:10:31
# /Users/josephsawaya/dev/test-result-action/demo/calculator/calculator.test.ts
# Users/josephsawaya/dev/test-result-action/demo/calculator/calculator.test.ts
file_path_regex = regex.compile(
    r"((\/*[\w\-]+\/)+([\w\.]+)(:\d+:\d+)*)",
)


def shorten_file_paths(string):
    """
    This function takes in a string and returns it with all the paths
    it contains longer than 3 components shortened to 3 components

    Example:
        string =    '''
            Expected: 1
            Received: -1
                at Object.&lt;anonymous&gt; (/Users/josephsawaya/dev/test-result-action/demo/calculator/calculator.test.ts:10:31)
                at Promise.then.completed (/Users/josephsawaya/dev/test-result-action/node_modules/jest-circus/build/utils.js:298:28)
        '''
        shortened_string = shorten_file_paths(string)
        print(shortened_string)

        will print:
            Expected: 1
            Received: -1
                at Object.&lt;anonymous&gt; (.../demo/calculator/calculator.test.ts:10:31)
                at Promise.then.completed (.../jest-circus/build/utils.js:298:28)
    """

    matches = file_path_regex.findall(string)
    for match_tuple in matches:
        file_path = match_tuple[0]
        split_file_path = file_path.split("/")

        # if the file_path has more than 3 components we should shorten it
        if len(split_file_path) > MAX_PATH_COMPONENTS:
            last_path_components = split_file_path[-MAX_PATH_COMPONENTS:]
            no_dots_shortened_file_path = "/".join(last_path_components)

            # possibly remove leading / because we're adding it with the dots
            if no_dots_shortened_file_path.startswith("/"):
                no_dots_shortened_file_path = no_dots_shortened_file_path[1:]

            shortened_path = ".../" + no_dots_shortened_file_path

            string = string.replace(file_path, shortened_path)

    return string
