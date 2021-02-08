# -*- coding: utf-8 -*-

import os

from .tree import Tree

relpath = os.path.relpath


def clean_path(path):
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


def _resolve_path(tree, path, ancestors=None):
    """
    Resolve a path

    :tree (Tree instance) Tree containing a lookup dictionary for paths
    :path (str) The path to be resolved
    :resolvers (list) Resolved changes

    returns new_path (str), pattern (list)
    """
    path = clean_path(path)

    new_path = tree.lookup(path, ancestors)

    if new_path:
        if ancestors and not _check_ancestors(path, new_path, ancestors):
            # path ancestor count is not valud
            return None

        return new_path

    # path was not resolved
    return None


def resolve_paths(toc, paths, ancestors=None):
    """
    Returns generated of resolved filepath names

    :toc (str) e.g, ",real_path,another_real_path,"
    :paths (list) e.g. ["path", "another_path"]
    """
    tree = Tree()
    tree.construct_tree(toc)
    # keep a cache of known changes
    for path in paths:
        new_path = _resolve_path(tree, path, ancestors)
        if new_path:
            # yield the match
            yield new_path
        else:
            yield None
