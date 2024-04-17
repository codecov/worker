from helpers.name_creator import global_name_creator


def test_name_generator():
    s = set()
    for _ in range(5):
        res = global_name_creator.create()
        assert len(res) == 8
        assert res not in s
        s.add(res)
    assert len(s) == 5  # all 5 created names are distinct
