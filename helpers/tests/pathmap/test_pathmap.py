from helpers.pathmap import (
    clean_path,
    _extract_match,
    _resolve_path,
    _check_ancestors,
    Tree,
)

# ========== Mock data ===========
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

toc = ["" if x is None else x for x in after]


# ========= END Mock data ==========
def test_clean_path():
    path = "**/some/directory"
    assert clean_path(path) == "some/directory"
    path = "some/path\r/with/tabs\r"
    assert clean_path(path) == "some/path/with/tabs"
    path = "some\ very_long/directory\ name"
    assert clean_path(path) == "some very_long/directory name"
    path = "ms\\style\\directory"
    assert clean_path(path) == "ms/style/directory"


def test_extract_match():
    toc = ",src/components/login.js,"
    index = toc.find("components")
    extracted = _extract_match(toc, index)
    assert extracted == "src/components/login.js"


def test_resolve_path():
    # short to long
    path = "Src/components/login.js"
    tree = Tree()
    tree.construct_tree(toc)
    new_path = _resolve_path(tree, path)
    assert new_path == "src/components/login.js"


def test_resolve_case():
    tree = Tree()
    tree.construct_tree(["Aa/Bb/cc", "Aa/Bb/Cc"])
    assert _resolve_path(tree, "aa/bb/cc") == "Aa/Bb/cc"
    assert _resolve_path(tree, "aa/bb/Cc") == "Aa/Bb/Cc"


def test_resolve_paths():
    tree = Tree()
    tree.construct_tree(toc)
    for path, expected in zip(before, after):
        assert _resolve_path(tree, path) == expected


def test_resolve_path_when_to_short():
    toc = ["a/b/c"]
    tree = Tree()
    tree.construct_tree(toc)
    assert _resolve_path(tree, "b/c", 0) == "a/b/c"
    assert _resolve_path(tree, "b/c", 1) == "a/b/c"


def test_resolve_path_when_to_long():
    toc = ["a/b/c"]
    tree = Tree()
    tree.construct_tree(toc)
    assert _resolve_path(tree, "z/y/b/c", 1) == "a/b/c"


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
    toc = ["x/y/z"]
    tree = Tree()
    tree.construct_tree(toc)

    # default, no ancestors ============================
    paths = ["z", "R/z", "R/y/z", "x/y/z", "w/x/y/z"]
    expected = ["x/y/z", "x/y/z", "x/y/z", "x/y/z", "x/y/z"]
    resolved = [_resolve_path(tree, path) for path in paths]
    assert resolved == expected

    # one ancestors ====================================
    paths = ["z", "R/z", "R/y/z", "x/y/z", "w/x/y/z"]
    expected = [None, None, "x/y/z", "x/y/z", "x/y/z"]
    resolved = [_resolve_path(tree, path, 1) for path in paths]
    assert set(resolved) == set(expected)

    # two ancestors ====================================
    paths = ["z", "R/z", "R/y/z", "x/y/z", "w/x/y/z"]
    expected = [None, None, None, "x/y/z", "x/y/z"]
    resolved = [_resolve_path(tree, path, 2) for path in paths]
    assert set(resolved) == set(expected)


def test_resolving():
    toc = ["a/b/c", "a/r/c", "c"]
    tree = Tree()
    tree.construct_tree(toc)
    assert _resolve_path(tree, "r/c", 1) == "a/r/c"
    assert _resolve_path(tree, "r/c") == "a/r/c"

    toc = ["a/b", "a/b/c/d", "x/y"]
    tree = Tree()
    tree.construct_tree(toc)
    assert _resolve_path(tree, "c/d", 1) == "a/b/c/d"


def test_with_plus():
    toc = ["b+c"]
    tree = Tree()
    tree.construct_tree(toc)
    assert _resolve_path(tree, "b+c") == "b+c"

    toc = ["a/b+c"]
    tree = Tree()
    tree.construct_tree(toc)
    assert _resolve_path(tree, "b+c") == "a/b+c"


def test_case_sensitive_ancestors():
    toc = ["src/HeapDump/GCHeapDump.cs"]
    tree = Tree()
    tree.construct_tree(toc)
    path = "C:/projects/perfview/src/heapDump/GCHeapDump.cs"
    new_path = _resolve_path(tree, path, 1)
    assert new_path == "src/HeapDump/GCHeapDump.cs"


def test_path_should_not_resolve():
    toc = ["four/six/three.py"]
    path = "four/six/seven.py"
    tree = Tree()
    tree.construct_tree(toc)
    path = _resolve_path(tree, path)
    assert path is None


def test_path_should_not_resolve_case_insensative():
    toc = ["a/b/C"]
    path = "a/B/c"
    tree = Tree()
    tree.construct_tree(toc)
    path = _resolve_path(tree, path)
    assert path == "a/b/C"


def test_ancestors_original_missing():
    toc = ["shorter.h"]
    tree = Tree()
    tree.construct_tree(toc)
    assert _resolve_path(tree, "a/long/path/shorter.h", 1) == "shorter.h"


def test_ancestors_absolute_path():
    toc = [
        "examples/ChurchNumerals.scala",
        "tests/src/test/scala/at/logic/gapt/examples/ChurchNumerals.scala",
    ]
    tree = Tree()
    tree.construct_tree(toc)
    path = "/home/travis/build/gapt/gapt/examples/ChurchNumerals.scala"

    assert _resolve_path(tree, path, 1) == "examples/ChurchNumerals.scala"
