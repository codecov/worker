import logging

from asgiref.sync import async_to_sync
from shared.celery_config import status_set_error_task_name
from shared.helpers.yaml import default_if_true
from shared.utils.urls import make_url

from app import celery_app
from database.models import Commit
from services.repository import get_repo_provider_service
from services.yaml import get_current_yaml
from services.yaml.reader import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StatusSetErrorTask(BaseCodecovTask, name=status_set_error_task_name):
    """
    Set commit status upon error
    """

    def run_impl(self, db_session, repoid, commitid, *, message=None, **kwargs):
        log.info(
            "Set error",
            extra=dict(repoid=repoid, commitid=commitid, description=message),
        )

        # TODO: need to check for enterprise license once licences are implemented
        # assert license.LICENSE['valid'], ('Notifications disabled. '+(license.LICENSE['warning'] or ''))

        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        repo_service = get_repo_provider_service(commit.repository)
        current_yaml = async_to_sync(get_current_yaml)(commit, repo_service)
        settings = read_yaml_field(current_yaml, ("coverage", "status"))

        status_set = False

        if settings and any(settings.values()):
            statuses = async_to_sync(repo_service.get_commit_statuses)(commitid)
            url = make_url(repo_service, "commit", commitid)
            for context in ("project", "patch", "changes"):
                if settings.get(context):
                    for key, data in default_if_true(settings[context]):
                        context = "codecov/%s%s" % (
                            context,
                            ("/" + key if key != "default" else ""),
                        )
                        state = (
                            "success"
                            if data.get("informational")
                            else data.get("if_ci_failed", "error")
                        )
                        message = (
                            message or "Coverage not measured fully because CI failed"
                        )
                        if context in statuses:
                            async_to_sync(repo_service.set_commit_status)(
                                commitid, state, context, message, url
                            )
                            status_set = True
                            log.info(
                                "Status set",
                                extra=dict(
                                    context=context, description=message, state=state
                                ),
                            )

        return {"status_set": status_set}


RegisteredStatusSetErrorTask = celery_app.register_task(StatusSetErrorTask())
status_set_error_task = celery_app.tasks[StatusSetErrorTask.name]
