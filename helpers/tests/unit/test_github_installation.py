from sqlalchemy.orm import Session

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    OwnerInstallationNameToUseForTask,
)
from database.tests.factories.core import OwnerFactory
from helpers.github_installation import get_installation_name_for_owner_for_task


def test_get_installation_name_for_owner_for_task(dbsession: Session):
    owner = OwnerFactory(service="github")
    other_owner = OwnerFactory()
    task_name = "app.tasks.notify.Notify"
    installation_task_config = OwnerInstallationNameToUseForTask(
        owner=owner,
        ownerid=owner.ownerid,
        installation_name="my_installation",
        task_name=task_name,
    )
    dbsession.add_all([owner, installation_task_config])
    dbsession.flush()
    assert (
        get_installation_name_for_owner_for_task(task_name, owner) == "my_installation"
    )
    assert (
        get_installation_name_for_owner_for_task(task_name, other_owner)
        == GITHUB_APP_INSTALLATION_DEFAULT_NAME
    )
    assert (
        get_installation_name_for_owner_for_task("other_task", owner)
        == GITHUB_APP_INSTALLATION_DEFAULT_NAME
    )
