from dataclasses import dataclass
from enum import Enum
from typing import List


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
