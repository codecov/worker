import mmh3


def calc_test_id(name: str, classname: str, testsuite: str) -> bytes:
    h = mmh3.mmh3_x64_128()  # assumes we're running on x64 machines
    h.update(testsuite.encode("utf-8"))
    h.update(classname.encode("utf-8"))
    h.update(name.encode("utf-8"))
    test_id_hash = h.digest()

    return test_id_hash
