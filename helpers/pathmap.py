from difflib import SequenceMatcher
from os.path import relpath
from typing import Sequence


def _clean_path(path):
    path = relpath(
        path.strip()
        .replace("**/", "")
        .replace("\r", "")
        .replace("\\ ", " ")
        .replace("\\", "/")
    )
    return path


def _check_ancestors(path, match, ancestors):
    """
    Require N ancestors to be in common with original path and matched path
    """
    pl = path.lower()
    ml = match.lower()
    if pl == ml:
        return True
    if len(ml.split("/")) < len(pl.split("/")) and pl.endswith(ml):
        return True
    return ml.endswith("/".join(pl.split("/")[(ancestors + 1) * -1 :]))


def _get_best_match(path: str, possibilities: list[str]) -> str:
    """
    Given a `path`, return the most similar one out of `possibilities`.
    """

    best_match = (-1, "")
    for possibility in possibilities:
        match = SequenceMatcher(None, path, possibility).ratio()
        if match > best_match[0]:
            best_match = (match, possibility)

    return best_match[1]


class Node:
    full_paths: list[str]
    """
    The full paths terminating in this node.
    """

    children: dict[str, "Node"]
    """
    Child nodes, keyed by path component.
    """

    def __init__(self) -> None:
        self.full_paths = []
        self.children = {}


class Tree:
    """
    This tree maintains a list of files and allows matching on them.

    It internally organizes the list of files (called `paths`) as a tree of `Node`s.
    The paths are split into path components in reverse order.
    Lookups in the tree also happen in reverse path-component order.

    For example, the following list of files:
    - `src/foo/mod.rs`
    - `src/foo/bar/mod.rs`

    ... are organized in a tree that looks like this:
    - mod.rs
      - foo
        - src => src/foo/mod.rs
      - bar
        - foo
          - src => src/foo/bar/mod.rs

    Using this tree, it is possible to look up paths like:
    - `C:\\Users\\ci\\repo\\src\\foo\\mod.rs`

    Matching / lookup again happens in reverse path-component order, from right to left.
    In this particular case, the tree traversal would walk the tree `Node`s `mod.rs`, `foo`, `src`
    before it hits the `src/foo/mod.rs` "full_path", which is the result of the lookup.
    """

    def __init__(self, paths: Sequence[str]):
        self.root = Node()
        for path in paths:
            self.insert(path)

    def insert(self, path: str):
        # the path components, in reverse order
        components = reversed(path.split("/"))

        node = self.root
        for component in components:
            component = component.lower()
            if component not in node.children:
                node.children[component] = Node()
            node = node.children[component]

        node.full_paths.append(path)

    def resolve_path(self, path: str, ancestors: int | None = None) -> str | None:
        path = _clean_path(path)
        new_path = self.lookup(path, ancestors)

        if new_path:
            if ancestors and not _check_ancestors(path, new_path, ancestors):
                # path ancestor count is not valid
                return None

            return new_path

        # path was not resolved
        return None

    def _drill(self, node: Node) -> str | None:
        """
        "Drill down" a straight branch of a tree, returning the first `full_paths`.
        """
        while len(node.children) == 1:
            node = next(iter(node.children.values()))
            if len(node.full_paths):
                return node.full_paths

        return None

    def _recursive_lookup(
        self,
        node: Node,
        components: list[str],
        results: list[str],
        i=0,
        end=False,
        match=False,
    ):
        """
        Performs a lookup in tree recursively

        :bool: end - Indicates if last lookup was the end of a sequence
        :bool: match - Indicates if filename has any match in tree
        """

        child_node = (
            node.children.get(components[i].lower()) if i < len(components) else None
        )
        if child_node:
            is_end = len(child_node.full_paths) > 0
            if is_end:
                results = child_node.full_paths
            return self._recursive_lookup(
                child_node, components, results, i + 1, is_end, True
            )
        else:
            if not end and match:
                next_path = self._drill(node)
                if next_path:
                    results.extend(next_path)
            return results

    def lookup(self, path: str, ancestors=None) -> str | None:
        """
        Lookup a path in the tree, returning the closest matching path
        in the tree if found.
        """
        path_hit = None
        components = list(reversed(path.split("/")))
        results = self._recursive_lookup(self.root, components, [])
        if not results:
            return None
        if len(results) == 1:
            path_hit = results[0]
        else:
            if path.replace(".", "").startswith("/") and ancestors:
                path_lengths = list(map(lambda x: len(x), results))
                closest_length = min(path_lengths, key=lambda x: abs(x - ancestors))
                path_hit = next(x for x in results if len(x) == closest_length)
            else:
                path_hit = _get_best_match(path, list(reversed(results)))
        return path_hit
