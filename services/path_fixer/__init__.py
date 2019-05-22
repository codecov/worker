from os.path import relpath
import typing
from collections import defaultdict

from pathmap import _resolve_path
from pathmap.tree import Tree

from services.path_fixer.fixpaths import _remove_known_bad_paths
from services.path_fixer.user_path_fixes import UserPathFixes
from services.path_fixer.user_path_includes import UserPathIncludes
from services.yaml import read_yaml_field


def invert_pattern(string: str) -> str:
    if string.startswith('!'):
        return string[1:]
    else:
        return '!%s' % string


class PathFixer(object):

    @classmethod
    def init_from_user_yaml(cls, commit_yaml: dict, toc: str, flags: typing.Sequence, base_path: str):
        path_patterns = list(
            map(
                invert_pattern,
                read_yaml_field(commit_yaml, ('ignore', )) or []
            )
        )
        if flags:
            for flag in flags:
                path_patterns.extend(
                    list(
                        map(
                            invert_pattern,
                            read_yaml_field(commit_yaml, ('flags', flag, 'ignore')) or []
                        )
                    )

                )
                path_patterns.extend(read_yaml_field(commit_yaml, ('flags', flag, 'paths')) or [])
        disable_default_path_fixes = read_yaml_field(commit_yaml, ('codecov', 'disable_default_path_fixes'))
        return cls(
            yaml_fixes=read_yaml_field(commit_yaml, ('fixes', )),
            path_patterns=path_patterns,
            toc=toc,
            should_disable_default_pathfixes=disable_default_path_fixes,
            base_path=base_path
        )

    def __init__(self, yaml_fixes, path_patterns, toc, should_disable_default_pathfixes=False, base_path=None):
        self.yaml_fixes = yaml_fixes or []
        self.path_patterns = set(path_patterns) or set([])
        self.toc = toc or []
        self.should_disable_default_pathfixes = should_disable_default_pathfixes
        self.base_path = base_path
        self.initialize()

    def initialize(self):
        self.custom_fixes = UserPathFixes(self.yaml_fixes)
        self.path_matcher = UserPathIncludes(self.path_patterns)
        self.tree = Tree()
        self.tree.construct_tree(self.toc)
        self.calculated_paths = defaultdict(set)

    def clean_path(self, path: str) -> str:
        if not path:
            return None
        path = relpath(
            path.replace('\\', '/')
                .lstrip('./')
                .lstrip('../')
        )
        if self.yaml_fixes:
            # applies pre
            path = self.custom_fixes(path, False)
        if self.toc and not self.should_disable_default_pathfixes:
            path = self.resolver(path, ancestors=1)
            if not path:
                return None
        elif not self.toc:
            path = _remove_known_bad_paths('', path)
        if self.yaml_fixes:
            # applied pre and post
            path = self.custom_fixes(path, True)
        if not self.path_matcher(path):
            return None
        return path

    def resolver(self, path: str, ancestors=None):
        return _resolve_path(self.tree, path, ancestors)

    def __call__(self, path: str) -> str:
        res = self.clean_path(path)
        self.calculated_paths[res].add(path)
        return res
