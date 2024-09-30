import logging

from sqlalchemy.orm import Session

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    Owner,
    OwnerInstallationNameToUseForTask,
)
from helpers.cache import cache

log = logging.getLogger(__file__)


@cache.cache_function(ttl=86400)  # 1 day
def get_installation_name_for_owner_for_task(
    dbsession: Session, task_name: str, owner: Owner
) -> str:
    config_for_owner = (
        dbsession.query(OwnerInstallationNameToUseForTask)
        .filter(
            OwnerInstallationNameToUseForTask.task_name == task_name,
            OwnerInstallationNameToUseForTask.ownerid == owner.ownerid,
        )
        .first()
    )
    if config_for_owner:
        log.info(
            "Owner has dedicated app for this task",
            extra=dict(this_task=task_name, ownerid=owner.ownerid),
        )
        return config_for_owner.installation_name
    return GITHUB_APP_INSTALLATION_DEFAULT_NAME
