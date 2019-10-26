class ReportExpiredException(Exception):
    pass


class ReportEmptyError(Exception):
    pass


class RepositoryWithoutValidBotError(Exception):
    pass

class OwnerWithoutOauthTokenError(Exception):
    pass
