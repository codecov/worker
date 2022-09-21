from helpers.match import match


def test_match():
    assert match(["old.*"], "new_branch") is False
    assert match(["new.*"], "new_branch") is True
    assert match(["old.*"], "new_branch") is False
    # Negative matches return False
    assert match(["!new.*"], "new_branch") is False
    assert match(["!new_branch"], "new_branch") is False
