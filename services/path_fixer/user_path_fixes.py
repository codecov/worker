import re
from typing import Sequence

from services.path_fixer.fixpaths import first_not_null_index, fixpaths_regs


class UserPathFixes(object):
    """
        This class contains the logic for apply path-fixes to the user, as described in
        https://docs.codecov.io/docs/fixing-paths

    There is an initializer and one function: __call__. The usage of it is:
        yaml_fixes = ['prefix_to_remove::', '::added_prefix', 'prefix_to_remove::add']
        upf = UserPathFixes(yaml_fixes)
        fixed_path = upf('simple/path.c')

    Attributes:
        regestry (A list of all fixes): Description
        sub_regex (re): Description
        yaml_fixes (Sequence[str]): Description
    """

    def __init__(self, yaml_fixes: Sequence[str]):
        self.yaml_fixes = yaml_fixes
        if self.yaml_fixes is None:
            self.yaml_fixes = []

        self._prefix = set(filter(lambda a: a[:2] == "::", self.yaml_fixes))
        custom_fixes = list(set(self.yaml_fixes) - self._prefix)
        if self._prefix:
            self._prefix = "/".join(
                list(map(lambda p: p[2:].rstrip("/"), self._prefix))[::-1]
            )
        if custom_fixes:
            # regestry = [result, result]
            self.regestry = list(
                map(lambda fix: tuple(fix.split("::"))[1], custom_fixes)
            )
            self.sub_regex = re.compile(
                r"^(%s)" % ")|(".join(map(fixpaths_regs, custom_fixes))
            )
        else:
            self.sub_regex = None

    def __call__(self, path: str, should_add_prefixes=True) -> str:
        if path:
            if should_add_prefixes and self._prefix:
                path = "%s/%s" % (self._prefix, path)
            if self.sub_regex:
                path = self.sub_regex.sub(
                    lambda m: self.regestry[first_not_null_index(m.groups())],
                    path,
                    count=1,
                )
            return path.replace("//", "/").lstrip("/")
        return None
