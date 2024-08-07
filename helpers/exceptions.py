import shared.bots.exceptions

RepositoryWithoutValidBotError = shared.bots.exceptions.RepositoryWithoutValidBotError
OwnerWithoutValidBotError = shared.bots.exceptions.OwnerWithoutValidBotError
RequestedGithubAppNotFound = shared.bots.exceptions.RequestedGithubAppNotFound
NoConfiguredAppsAvailable = shared.bots.exceptions.NoConfiguredAppsAvailable


class ReportExpiredException(Exception):
    def __init__(self, message=None, filename=None) -> None:
        super().__init__(message)
        self.filename = filename


class ReportEmptyError(Exception):
    pass


class CorruptRawReportError(Exception):
    """Error indicated that report is somehow different than it should be

    Notice that this error should not be used to replace `matches_content` logic on each processor.
        For header/top-level or even deeper checks that are quick and O(1), the method
        `matches_content` should be used. Its purpose is to quickly look at the file and try to
        determine which processor can handle it.

    This error is meant for when the report header/top-level information truly indicated the file
        format was X and could be read by processorX, and then something deep down the file did not
        properly match this file expected structure, and it this could not be checked beforehand
        without doing some parsing as complete as the actual processing of the file

    The an example of such logic, see `VOneProcessor`. It is impractical there to check every
        file dict to see if any of them do not have the proper format

    Attributes:
        corruption_error (str): A short description of the unexpected issue
        expected_format (str): What format the file was expcted to have. Can be an actual format
            name, or some identifier for people to understand what is the right structure to follow
    """

    def __init__(self, expected_format: str, corruption_error: str):
        super().__init__(expected_format, corruption_error)
        self.expected_format = expected_format
        self.corruption_error = corruption_error
