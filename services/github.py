import logging
from typing import Optional

from shared.github import InvalidInstallationError
from shared.github import get_github_integration_token as _get_github_integration_token
from shared.github import is_installation_rate_limited

from helpers.cache import cache
from helpers.exceptions import RepositoryWithoutValidBotError

log = logging.getLogger(__name__)


@cache.cache_function(ttl=480)
def get_github_integration_token(
    service,
    integration_id=None,
    app_id: Optional[str] = None,
    pem_path: Optional[str] = None,
):
    try:
        return _get_github_integration_token(
            service, integration_id=integration_id, app_id=app_id, pem_path=pem_path
        )
    except InvalidInstallationError:
        log.warning("Failed to get installation token")
        raise RepositoryWithoutValidBotError()
