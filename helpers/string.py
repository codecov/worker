from dataclasses import dataclass
from enum import Enum
from typing import List


class EscapeEnum(Enum):
    APPEND = "append"
    PREPEND = "prepend"
    REPLACE = "replace"


@dataclass
class Replacement:
    chars: str
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
                Replacement("1", "2", EscapeEnum.APPEND),
                Replacement("3", "4", EscapeEnum.PREPEND),
                Replacement("5", "6", EscapeEnum.REPLACE),
            ]

            escaper = StringEscaper(escape_def)

            escaper.replace("123456")

            will give: "12243466"
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
