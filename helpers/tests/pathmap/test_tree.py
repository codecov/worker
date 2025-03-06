from helpers.pathmap import Tree, _get_best_match


def test_get_best_match():
    path = "a/bB.py"
    possibilities = ["c/bB.py", "d/Bb.py"]

    assert _get_best_match(path, possibilities) == "c/bB.py"


def test_drill():
    tree = Tree(["a/b/c"])
    assert tree._drill(tree.root) == ["a/b/c"]


def test_drill_multiple_possible_paths():
    tree = Tree(["src/list.rs", "benches/list.rs"])

    branch = tree.root.children.get("list.rs")
    assert tree._drill(branch) is None


def test_recursive_lookup():
    path = "one/two/three.py"

    tree = Tree([path])

    path_split = list(reversed(path.split("/")))
    match = tree._recursive_lookup(tree.root, path_split, [])

    assert match == ["one/two/three.py"]

    path = "four/five/three.py"
    path_split = list(reversed(path.split("/")))
    match = tree._recursive_lookup(tree.root, path_split, [])

    assert match == ["one/two/three.py"]


def test_lookup():
    tree = Tree(["one/two/three.py"])

    assert tree.lookup("two/one/three.py") == "one/two/three.py"
