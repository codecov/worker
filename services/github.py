import logging

from shared.github import InvalidInstallationError
from shared.github import get_github_integration_token as _get_github_integration_token

from helpers.cache import cache
from helpers.exceptions import RepositoryWithoutValidBotError

log = logging.getLogger(__name__)


@cache.cache_function(ttl=480)
def get_github_integration_token(service, integration_id=None):
    try:
        return _get_github_integration_token(service, integration_id=integration_id)
    except InvalidInstallationError:
        log.warning("Failed to get installation token")
        raise RepositoryWithoutValidBotError()
