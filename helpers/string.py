from enum import Enum
from typing import List


class EscapeEnum(Enum):
    APPEND = "append"
    PREPEND = "prepend"
    REPLACE = "replace"


class Replacement:
    def __init__(self, chars: str, output: str, method: EscapeEnum):
        self.chars = chars
        self.output = output
        self.method = method


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
                Replacement(chars="<>", output="\\", method=EscapeEnum.PREPEND),
                Replacement(chars="pre", output="div", method=EscapeEnum.REPLACE)
            ]
            StringEscaper(escape_def)

            replace("<pre></pre>")

            will give: \<div\>\</div\>
    """

    def __init__(self, escape_def: List[Replacement]):
        self.escape_def = escape_def

    def replace(self, string):
        for replacement in self.escape_def:
            for char in replacement.chars:
                if replacement.method == EscapeEnum.PREPEND:
                    string = string.replace(char, f"{replacement.output}{char}")
                elif replacement.method == EscapeEnum.APPEND:
                    string = string.replace(char, f"{char}{replacement.output}")
                elif replacement.method == EscapeEnum.REPLACE:
                    string = string.replace(char, replacement.output)
        return string
