import mmh3


def calc_test_id(name: str, classname: str, testsuite: str) -> bytes:
    h = mmh3.mmh3_x64_128()  # assumes we're running on x64 machines
    h.update(testsuite.encode("utf-8"))
    h.update(classname.encode("utf-8"))
    h.update(name.encode("utf-8"))
    test_id_hash = h.digest()

    return test_id_hash


def calc_flags_hash(flags: list[str]) -> bytes | None:
    flags_str = " ".join(sorted(flags))  # we know that flags cannot contain spaces

    # returns a tuple of two int64 values
    # we only need the first one
    flags_hash, _ = mmh3.hash64(flags_str, signed=False)
    flags_hash_bytes = flags_hash.to_bytes(8)
    return flags_hash_bytes
