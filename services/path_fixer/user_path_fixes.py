import re

_star_to_glob = re.compile(r"(?<!\.)\*").sub


def _fixpaths_regs(fix: str) -> str:
    # [DEPRECATED] because handled by validators, but some data is cached in db
    # a/**/b => a/.*/b
    fix = fix.replace("**", r".*")
    # a/*/b => a/[^\/\n]+/b
    fix = _star_to_glob(r"[^\/\n]+", fix)
    return fix.lstrip("/")


class UserPathFixes:
    """
    This class contains the logic for apply path-fixes to the user, as described in
    https://docs.codecov.io/docs/fixing-paths

    There is an initializer and one function: __call__.
    The usage of it is:

        yaml_fixes = ['prefix_to_remove::', '::added_prefix', 'prefix_to_remove::add']
        upf = UserPathFixes(yaml_fixes)
        fixed_path = upf('simple/path.c')
    """

    yaml_fixes: list[str]

    prefix: str
    sub_regex: re.Pattern | None
    sub_replacements: list[str]

    def __init__(self, yaml_fixes: list[str] | None):
        yaml_fixes = yaml_fixes or []
        self.yaml_fixes = yaml_fixes
        self.prefix = ""
        self.sub_regex = None
        self.sub_replacements = []

        prefixes = set(f for f in yaml_fixes if f.startswith("::"))
        custom_fixes = list(set(yaml_fixes) - prefixes)

        if prefixes:
            self.prefix = "/".join(p[2:].rstrip("/") for p in prefixes)

        if custom_fixes:
            self.sub_regex = re.compile(
                r"^(%s)"
                % ")|(".join(_fixpaths_regs(fix.split("::")[0]) for fix in custom_fixes)
            )
            self.sub_replacements = [fix.split("::")[1] for fix in custom_fixes]

    def _replacement_fn(self, group: re.Match) -> str:
        for group, replacement in zip(group.groups(), self.sub_replacements):
            if group:
                return replacement
        assert False, "unreachable"  # this is only ever called with one truthy group

    def __call__(self, path: str, should_add_prefixes=True) -> str:
        if should_add_prefixes and self.prefix:
            path = "%s/%s" % (self.prefix, path)

        if self.sub_regex:
            path = self.sub_regex.sub(
                self._replacement_fn,
                path,
                count=1,
            )

        return path.replace("//", "/").lstrip("/")
