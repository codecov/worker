import logging

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    Owner,
    OwnerInstallationNameToUseForTask,
)

log = logging.getLogger(__file__)


def get_installation_name_for_owner_for_task(task_name: str, owner: Owner) -> str:
    if owner.service not in ["github", "github_enterprise"]:
        # The `installation` concept only exists in GitHub.
        # We still return a default here, primarily to satisfy types.
        return GITHUB_APP_INSTALLATION_DEFAULT_NAME

    dbsession = owner.get_db_session()
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
