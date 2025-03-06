from helpers.pathmap import Tree, _check_ancestors, _clean_path


def test_clean_path():
    path = "**/some/directory"
    assert _clean_path(path) == "some/directory"
    path = "some/path\r/with/tabs\r"
    assert _clean_path(path) == "some/path/with/tabs"
    path = "some\\ very_long/directory\\ name"
    assert _clean_path(path) == "some very_long/directory name"
    path = "ms\\style\\directory"
    assert _clean_path(path) == "ms/style/directory"


def test_resolve_path():
    tree = Tree(["src/components/login.js"])

    assert tree.resolve_path("Src/components/login.js") == "src/components/login.js"


def test_resolve_case():
    tree = Tree(["Aa/Bb/cc", "Aa/Bb/Cc"])
    assert tree.resolve_path("aa/bb/cc") == "Aa/Bb/cc"
    assert tree.resolve_path("aa/bb/Cc") == "Aa/Bb/Cc"


def test_resolve_paths():
    before = [
        "not/found.py",
        "/Users/user/owner/repo/src/components/login.js",
        "site-packages/package/__init__.py",
        "path.py",
        "a/b/../Path With\\ Space",
    ]

    after = [
        None,
        "src/components/login.js",
        "package/__init__.py",
        "path.py",
        "a/Path With Space",
    ]

    tree = Tree([path for path in after if path])
    for path, expected in zip(before, after):
        assert tree.resolve_path(path) == expected


def test_resolve_path_when_to_short():
    tree = Tree(["a/b/c"])
    assert tree.resolve_path("b/c", 0) == "a/b/c"
    assert tree.resolve_path("b/c", 1) == "a/b/c"


def test_resolve_path_when_to_long():
    tree = Tree(["a/b/c"])
    assert tree.resolve_path("z/y/b/c", 1) == "a/b/c"


def test_check_ancestors():
    assert _check_ancestors("a", "a", 1) is True, "matches"
    assert _check_ancestors("A", "a", 1) is True, "matches case insensative"
    assert _check_ancestors("a/B", "a/B", 1) is True, "matches"
    assert _check_ancestors("A/B", "a/b", 1) is True, "matches case insensative"
    assert _check_ancestors("b/b", "a/b", 1) is False, "does not match first ancestor"
    assert _check_ancestors("a/b/c", "x/b/c", 1) is True
    assert _check_ancestors("a/b/c", "x/b/c", 2) is False
    assert _check_ancestors("a/b/c/d", "X/B/C/D", 2) is True
    assert _check_ancestors("a", "b/a", 2) is True, "original was missing ancestors"
    assert _check_ancestors("a/b", "z/a/b", 2) is True
    assert _check_ancestors("b", "a/b", 1) is True


def test_resolve_paths_with_ancestors():
    tree = Tree(["x/y/z"])

    # default, no ancestors ============================
    paths = ["z", "R/z", "R/y/z", "x/y/z", "w/x/y/z"]
    expected = ["x/y/z", "x/y/z", "x/y/z", "x/y/z", "x/y/z"]
    resolved = [tree.resolve_path(path) for path in paths]
    assert resolved == expected

    # one ancestors ====================================
    paths = ["z", "R/z", "R/y/z", "x/y/z", "w/x/y/z"]
    expected = [None, None, "x/y/z", "x/y/z", "x/y/z"]
    resolved = [tree.resolve_path(path, 1) for path in paths]
    assert set(resolved) == set(expected)

    # two ancestors ====================================
    paths = ["z", "R/z", "R/y/z", "x/y/z", "w/x/y/z"]
    expected = [None, None, None, "x/y/z", "x/y/z"]
    resolved = [tree.resolve_path(path, 2) for path in paths]
    assert set(resolved) == set(expected)


def test_resolving():
    tree = Tree(["a/b/c", "a/r/c", "c"])
    assert tree.resolve_path("r/c", 1) == "a/r/c"
    assert tree.resolve_path("r/c") == "a/r/c"

    tree = Tree(["a/b", "a/b/c/d", "x/y"])
    assert tree.resolve_path("c/d", 1) == "a/b/c/d"


def test_with_plus():
    tree = Tree(["b+c"])
    assert tree.resolve_path("b+c") == "b+c"

    tree = Tree(["a/b+c"])
    assert tree.resolve_path("b+c") == "a/b+c"


def test_case_sensitive_ancestors():
    tree = Tree(["src/HeapDump/GCHeapDump.cs"])
    path = "C:/projects/perfview/src/heapDump/GCHeapDump.cs"
    new_path = tree.resolve_path(path, 1)
    assert new_path == "src/HeapDump/GCHeapDump.cs"


def test_path_should_not_resolve():
    tree = Tree(["four/six/three.py"])
    assert tree.resolve_path("four/six/seven.py") is None


def test_path_should_not_resolve_case_insensative():
    tree = Tree(["a/b/C"])
    assert tree.resolve_path("a/B/c") == "a/b/C"


def test_ancestors_original_missing():
    tree = Tree(["shorter.h"])
    assert tree.resolve_path("a/long/path/shorter.h", 1) == "shorter.h"


def test_ancestors_absolute_path():
    tree = Tree(
        [
            "examples/ChurchNumerals.scala",
            "tests/src/test/scala/at/logic/gapt/examples/ChurchNumerals.scala",
        ]
    )
    path = "/home/travis/build/gapt/gapt/examples/ChurchNumerals.scala"

    assert tree.resolve_path(path, 1) == "examples/ChurchNumerals.scala"
