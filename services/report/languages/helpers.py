from dataclasses import dataclass
from xml.etree.ElementTree import Element


def remove_non_ascii(string: str) -> str:
    # ASCII control characters <=31, 127
    # Extended ASCII characters: >=128
    return "".join(c if 31 < ord(c) < 127 else "" for c in string)


def child_text(parent: Element, element: str) -> str:
    """
    Returns the text content of the first element of type `element` of `parent`.

    This defaults to the empty string if no child is found, or the child does not have any text.
    """
    child = parent.find(element)
    if child is None:
        return ""
    return child.text or ""


@dataclass
class SourceLocation:
    line: int
    column: int


@dataclass
class Region:
    start: SourceLocation
    end: SourceLocation
    hits: int
