import re

from services.path_fixer.match import regexp_match_one


class UserPathIncludes:
    """
    This class has one purpose: To determine whether a specific path should
    be included in the report or not/

    Its usage is:

        path_patterns = ['.*', 'whatever']
        upi = UserPathIncludes(path_patterns)
        should_be_included = upi('sample/path/to/file.go')
    """

    path_patterns: set[str]

    includes: list[re.Pattern]
    include_all: bool

    excludes: list[re.Pattern]
    exclude_all: bool

    def __init__(self, path_patterns: set[str], assume=True):
        self.path_patterns = path_patterns
        self.includes = []
        self.include_all = False
        self.excludes = []
        self.exclude_all = False

        if not self.path_patterns:
            return

        includes = set(p for p in path_patterns if not p.startswith("!"))
        excludes = set(path_patterns) - includes

        # create lists of pass/fails
        if ".*" in path_patterns:
            # match everything, just make sure it is not negative
            self.include_all = True
            self.includes = []
        elif assume and len(includes) == 0:
            self.include_all = True
        else:
            self.include_all = False
            self.includes = [re.compile(i) for i in includes]

        if "!.*" in self.path_patterns:
            self.exclude_all = False
        else:
            self.excludes = [re.compile(e[1:]) for e in excludes]

    def __call__(self, value: str) -> bool:
        if not self.path_patterns:
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
