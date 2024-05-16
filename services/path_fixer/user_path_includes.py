import re
import typing

from services.path_fixer.match import regexp_match_one


class UserPathIncludes(object):
    """
        This class has one purpose: To determine whether a specific path should
            be included in the report or not/

        Its usage is:

            path_patterns = ['.*', 'whatever']
            upi = UserPathIncludes(path_patterns)
            should_be_included = upi('sample/path/to/file.go')

    Attributes:
        excludes (typing.Sequence[str]): The patterns that should excluded
        include_all (bool): Whether all path should be included except on `exclude` list
        includes (typing.Sequence[str]): The patterns that should be included
        path_patterns (typing.Sequence[str]): The paths inputted by the user
    """

    def __init__(self, path_patterns: typing.Sequence[str], assume=True):
        self.path_patterns = path_patterns
        if not self.path_patterns:
            return

        self.includes = set(filter(lambda p: not p.startswith("!"), self.path_patterns))
        self.excludes = set(self.path_patterns) - self.includes

        # create lists of pass/fails
        if ".*" in self.path_patterns:
            # match everything, just make sure it is not negative
            self.include_all = True
            self.includes = None
        elif assume and len(self.includes) == 0:
            self.include_all = True
        else:
            self.include_all = False
            self.includes = list(map(re.compile, self.includes))

        if "!.*" in self.path_patterns:
            self.exclude_all = False
        else:
            self.excludes = list(
                map(
                    lambda p: re.compile(p[1:]),
                    filter(lambda p: p.startswith("!"), self.path_patterns),
                )
            )

    def __call__(self, value: str) -> bool:
        if not set(self.path_patterns):
            return True
        if value:
            if self.include_all:
                # everything is included
                if self.excludes:
                    # make sure it is not excluded
                    return not regexp_match_one(self.excludes, value)
                else:
                    return True
            # we have to match once
            if regexp_match_one(self.includes, value) is True:
                # make sure it's not excluded
                if self.excludes and regexp_match_one(self.excludes, value):
                    return False
                else:
                    return True
            return False
        return False
