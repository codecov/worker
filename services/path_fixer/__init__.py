import logging
import os.path
import random
from collections import defaultdict
from pathlib import PurePath

import sentry_sdk
from shared.yaml import UserYaml

from helpers.pathmap import Tree
from services.path_fixer.fixpaths import remove_known_bad_paths
from services.path_fixer.user_path_fixes import UserPathFixes
from services.path_fixer.user_path_includes import UserPathIncludes
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


def invert_pattern(string: str) -> str:
    if string.startswith("!"):
        return string[1:]
    else:
        return "!%s" % string


class PathFixer(object):
    """
    Applies default path fixes and any fixes specified in the codecov yaml file to resolve file paths in coverage reports.
    Also applies any "ignore" and "paths" yaml fields to determine which files to include in the report.
    """

    tree: Tree | None

    @classmethod
    @sentry_sdk.trace
    def init_from_user_yaml(
        cls,
        commit_yaml: UserYaml,
        toc: list[str],
        flags: list[str] | None = None,
        extra_fixes: list[str] | None = None,
    ):
        """
        :param commit_yaml: Codecov yaml file in effect for this commit.
        :param toc: List of files prepended to the uploaded report. Not all report formats provide this.
        :param flags: Coverage flags specified by the user, if any.
        """
        ignore = read_yaml_field(commit_yaml, ("ignore",)) or []
        path_patterns = [invert_pattern(p) for p in ignore]

        for flag in flags or []:
            flag_configuration = commit_yaml.get_flag_configuration(flag) or {}
            path_patterns.extend(
                invert_pattern(p) for p in flag_configuration.get("ignore") or []
            )
            path_patterns.extend(flag_configuration.get("paths") or [])

        disable_default_path_fixes = read_yaml_field(
            commit_yaml, ("codecov", "disable_default_path_fixes")
        )
        yaml_fixes = read_yaml_field(commit_yaml, ("fixes",)) or []

        if extra_fixes:
            yaml_fixes.extend(extra_fixes)

        return cls(
            yaml_fixes=yaml_fixes,
            path_patterns=path_patterns,
            toc=toc,
            should_disable_default_pathfixes=disable_default_path_fixes,
        )

    def __init__(
        self,
        yaml_fixes: list[str],
        path_patterns: list[str],
        toc: list[str],
        should_disable_default_pathfixes=False,
    ) -> None:
        self.calculated_paths: dict[str | None, set[str]] = defaultdict(set)
        self.toc = toc or []

        self.yaml_fixes = yaml_fixes or []
        self.path_patterns = set(path_patterns) or set([])
        self.should_disable_default_pathfixes = should_disable_default_pathfixes

        self.custom_fixes = UserPathFixes(self.yaml_fixes)
        self.path_matcher = UserPathIncludes(self.path_patterns)

        if self.toc and not should_disable_default_pathfixes:
            self.tree = Tree(self.toc)
        else:
            self.tree = None

    def clean_path(self, path: str | None) -> str | None:
        if not path:
            return None
        path = os.path.relpath(path.replace("\\", "/").lstrip("./").lstrip("../"))
        if self.yaml_fixes:
            # applies pre
            path = self.custom_fixes(path, False)
        if self.tree:
            path = self.tree.resolve_path(path, ancestors=1)
            if not path:
                return None
        elif not self.toc:
            path = remove_known_bad_paths("", path)
        if self.yaml_fixes:
            # applied pre and post
            path = self.custom_fixes(path, True)
        if not self.path_matcher(path):
            # don't include the file if yaml specified paths to include/ignore and it's not in the list to include
            return None
        return path

    def __call__(self, path: str, bases_to_try=None) -> str | None:
        res = self.clean_path(path)
        self.calculated_paths[res].add(path)
        return res

    def get_relative_path_aware_pathfixer(self, base_path) -> "BasePathAwarePathFixer":
        return BasePathAwarePathFixer(original_path_fixer=self, base_path=base_path)


class BasePathAwarePathFixer(PathFixer):
    def __init__(self, original_path_fixer, base_path) -> None:
        self.original_path_fixer = original_path_fixer
        self.unexpected_results: list[dict] = []

        # base_path argument is the file path after the "# path=" in the report containing report location, if provided.
        # to get the base path we use, strip the coverage report from the path to get the base path
        # e.g.: "path/to/coverage.xml" --> "path/to/"
        self.base_path = [PurePath(base_path).parent] if base_path is not None else []

    def __call__(self, path: str, bases_to_try: list[str] | None = None) -> str | None:
        original_path_fixer_result = self.original_path_fixer(path)
        if (
            original_path_fixer_result is not None
            or (not self.base_path and not bases_to_try)
            or not self.original_path_fixer.toc
        ):
            return original_path_fixer_result
        if not os.path.isabs(path):
            all_base_paths_to_try = self.base_path + (
                bases_to_try if bases_to_try is not None else []
            )
            for base_path in all_base_paths_to_try:
                adjusted_path = os.path.join(base_path, path)
                base_path_aware_result = self.original_path_fixer(adjusted_path)
                if base_path_aware_result is not None:
                    self.unexpected_results.append(
                        {
                            "original_path": path,
                            "original_path_fixer_result": original_path_fixer_result,
                            "base_path_aware_result": base_path_aware_result,
                        }
                    )
                    return base_path_aware_result
        return original_path_fixer_result

    def log_abnormalities(self) -> bool:
        """
            Analyze whether there were abnormalities in this pathfixer processing.
        Returns:
            bool: Whether abnormalities were noted or not
        """
        if len(self.unexpected_results) > 0:
            log.info(
                "Paths did not match due to the relative path calculation",
                extra=dict(
                    base=self.base_path,
                    path_patterns=sorted(self.original_path_fixer.path_patterns),
                    yaml_fixes=self.original_path_fixer.yaml_fixes,
                    some_cases=random.sample(
                        self.unexpected_results, min(50, len(self.unexpected_results))
                    ),
                ),
            )
            return True
        return False
