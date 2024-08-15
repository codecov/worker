class ComparisonError(Exception):
    pass


class MissingBaseCommit(ComparisonError):
    pass


class MissingBaseReport(ComparisonError):
    pass


class MissingHeadCommit(ComparisonError):
    pass


class MissingHeadReport(ComparisonError):
    pass
