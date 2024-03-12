from services.failure_normalizer import FailureNormalizer

test_string = "abcdefAB-1234-1234-1234-abcdefabcdef 2024-03-10 test 0x44358378"


def test_failure_normalizer():
    user_dict = {"HEX": r"0x\d{8}"}
    f = FailureNormalizer(user_dict)
    s = f.normalize_failure_message(test_string)

    assert s == "UUID DATE test HEX"


def test_failure_normalizer_ignore_predefined():
    user_dict = {"HEX": r"0x\d{8}"}
    f = FailureNormalizer(user_dict, True)
    s = f.normalize_failure_message(test_string)

    assert s == "abcdefAB-1234-1234-1234-abcdefabcdef 2024-03-10 test HEX"


def test_failure_normalizer_overwrite_predefined():
    user_dict = {"UUID": "test", "HEX": r"0x\d{8}"}
    f = FailureNormalizer(user_dict)
    s = f.normalize_failure_message(test_string)

    assert s == "abcdefAB-1234-1234-1234-abcdefabcdef DATE UUID HEX"
