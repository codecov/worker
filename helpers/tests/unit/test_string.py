from helpers.string import EscapeEnum, Replacement, StringEscaper


def test_string_escaper():
    escape_def = [
        Replacement("1", "2", EscapeEnum.APPEND),
        Replacement("3", "4", EscapeEnum.PREPEND),
        Replacement("5", "6", EscapeEnum.REPLACE),
    ]

    escaper = StringEscaper(escape_def)

    assert escaper.replace("123456") == "12243466"
