from helpers.pathmap import Tree


class TestTree(object):
    @classmethod
    def setup_class(cls):
        cls.tree = Tree()

    def setup_method(self, method):
        self.tree.instance = {}

    def test_list_to_nested_dict(self):
        keys = ["a", "b", "c"]
        nested_dict = self.tree._list_to_nested_dict(keys)

        leaf = nested_dict.get("c").get("b").get("a")

        assert leaf
        assert leaf.get(self.tree._END)
        assert leaf.get(self.tree._ORIG) == ["a/b/c"]

    def test_get_best_match(self):
        path = "a/bB.py"
        possibilities = ["c/bB.py", "d/Bb.py"]

        match = self.tree._get_best_match(path, possibilities)

        assert match == "c/bB.py"

    def test_drill(self):
        """
        Test drilling a branch of tree
        """

        nested = self.tree._list_to_nested_dict(["a", "b", "c"])
        assert self.tree._drill(nested, []) == ["a/b/c"]

    def test_drill_multiple_possible_paths(self):
        toc = ["src/list.rs", "benches/list.rs"]
        self.tree.construct_tree(toc)

        branch = self.tree.instance.get("list.rs")
        results = []
        assert self.tree._drill(branch, results) is None

    def test_recursive_lookup(self):
        path = "one/two/three.py"

        self.tree.construct_tree([path])

        path_split = list(reversed(path.split("/")))
        match = self.tree._recursive_lookup(self.tree.instance, path_split, [])

        assert match == ["one/two/three.py"]

        path = "four/five/three.py"
        path_split = list(reversed(path.split("/")))
        match = self.tree._recursive_lookup(self.tree.instance, path_split, [])

        assert match == ["one/two/three.py"]

    def test_lookup(self):
        toc = ["one/two/three.py"]
        path = "two/one/three.py"
        self.tree.construct_tree(toc)

        assert self.tree.lookup(path) == "one/two/three.py"

    def test_update(self):
        dict1 = self.tree._list_to_nested_dict(["a", "b", "c"])
        dict2 = self.tree._list_to_nested_dict(["e", "g", "c"])

        updated = self.tree.update(dict1, dict2)

        assert updated.get("c").get("b").get("a")
        assert updated.get("c").get("g").get("e")

    def test_insert(self):
        path = "a/b/c.py"
        self.tree.insert(path)

        assert self.tree.instance.get("c.py").get("b").get("a")

    def test_construct_tree(self):
        toc = ["a/b/c"]

        self.tree.construct_tree(toc)
        assert self.tree.instance.get("c").get("b").get("a")
