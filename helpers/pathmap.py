import collections
import operator
from difflib import SequenceMatcher
from os.path import relpath


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


class Tree:
    def __init__(self, *args, **kwargs):
        self.instance = {}

        # Sequence end indicator
        self._END = "\\*__ends__*//"

        # Original value indicator
        self._ORIG = "\\*__orig__*//"

    def resolve_path(self, path: str, ancestors=None):
        path = _clean_path(path)

        new_path = self.lookup(path, ancestors)

        if new_path:
            if ancestors and not _check_ancestors(path, new_path, ancestors):
                # path ancestor count is not valud
                return None

            return new_path

        # path was not resolved
        return None

    def _list_to_nested_dict(self, lis):
        """
        Turns a list into a nested dict

        E.g.:
            ['a','b','c'] => { 'c' : { 'b' : { 'a' : {} } } }
        """
        d = {}
        for i in range(0, len(lis)):
            d[self._END] = True if i == 0 else False
            d[self._ORIG] = ["/".join(lis[i:])]
            d = {lis[i].lower(): d}
        return d

    def _get_best_match(self, path, possibilities):
        """
        Given a path find how similar it is to all paths in possibilities

        :str: path - A path part E.g.: a/b.py => a
        :list: possibilities - Collected possibilities
        """

        # Map out similarity of possible paths with the path being looked up
        similarity = list(
            map(lambda x: SequenceMatcher(None, path, x).ratio(), possibilities)
        )

        # Get the index, value of the most similar path
        index, value = max(enumerate(similarity), key=operator.itemgetter(1))

        return possibilities[index]

    def _drill(self, d, results):
        """
        Drill down a branch of a tree.
        Collects results until a ._END is reached.

        :returns - A list containing a possible path or None
        """
        root_keys = [x for x in d.keys() if x != self._ORIG and x != self._END]

        if len(root_keys) > 1 or not root_keys:
            return None

        root_key = root_keys[0]
        root = d.get(root_key)

        if root.get(self._END):
            return root.get(self._ORIG)
        else:
            return self._drill(root, results)

    def _recursive_lookup(self, d, lis, results, i=0, end=False, match=False):
        """
        Performs a lookup in tree recursively

        :dict: d - tree branch
        :list: lis - list of strings to search for
        :list: results - Collected hit results
        :int: i - Index of lis
        :bool: end - Indicates if last lookup was the end of a sequence
        :bool: match - Indicates if filename has any match in tree

        :returns a list of hit results if path is found in the tree
        """
        key = None

        if i < len(lis):
            key = lis[i].lower()

        root = d.get(key)
        if root:
            if root.get(self._END):
                results = root.get(self._ORIG)
            return self._recursive_lookup(
                root, lis, results, i + 1, root.get(self._END), True
            )
        else:
            if not end and match:
                next_path = self._drill(d, results)
                if next_path:
                    results.extend(next_path)
            return results

    def lookup(self, path, ancestors=None):
        """
        Lookup a path in the tree

        :str: path - The path to search for

        :returns The closest matching path in the tree if present else None
        """
        path_hit = None
        path_split = list(reversed(path.split("/")))
        results = self._recursive_lookup(self.instance, path_split, [])

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
                path_hit = self._get_best_match(path, list(reversed(results)))

        return path_hit

    def update(self, d, u):
        """
        Update a dictionary
        :dict: d - Dictionary being updated
        :dict: u - Dictionary being merged
        """
        for k, v in u.items():
            if isinstance(v, collections.abc.Mapping):
                r = self.update(d.get(k, {}), v)
                d[k] = r
            else:
                if k == self._END and d.get(k) is True:
                    pass
                elif k == self._ORIG and d.get(k) and u.get(k):
                    if d[k] != u[k]:
                        d[k] = d[k] + u[k]
                else:
                    d[k] = u[k]
        return d

    def insert(self, path):
        """
        Insert a path into the tree

        :str: path - The path to insert
        """

        path_split = path.split("/")
        root_key = path_split[-1].lower()
        root = self.instance.get(root_key)

        if not root:
            u = self._list_to_nested_dict(path_split)
            self.instance.update(u)
        else:
            u = self._list_to_nested_dict(path_split)
            self.instance = self.update(self.instance, u)

    def construct_tree(self, toc):
        """
        Constructs a tree

        :list: toc - The table of contents
        """

        for path in toc:
            self.insert(path)
