import logging

from app import celery_app
from celery_config import status_set_pending_task_name
from covreports.helpers.yaml import default_if_true
from covreports.utils.match import match
from covreports.utils.urls import make_url

from database.models import Commit
from services.redis import get_redis_connection
from services.repository import get_repo_provider_service
from services.yaml import get_current_yaml
from services.yaml.reader import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StatusSetPendingTask(BaseCodecovTask):
    """
    Set commit status to pending
    """

    name = status_set_pending_task_name

    async def run_async(
        self, db_session, repoid, commitid, branch, on_a_pull_request, *args, **kwargs
    ):
        log.info(
            "Set pending",
            extra=dict(
                repoid=repoid,
                commitid=commitid,
                branch=branch,
                on_a_pull_request=on_a_pull_request,
            ),
        )

        # TODO: need to check for enterprise license once licences are implemented
        # assert license.LICENSE['valid'], ('Notifications disabled. '+(license.LICENSE['warning'] or ''))

        # check that repo is in beta
        redis_connection = get_redis_connection()
        assert redis_connection.sismember(
            "beta.pending", repoid
        ), "Pending disabled. Please request to be in beta."

        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."
        repo_service = get_repo_provider_service(commit.repository)
        current_yaml = await get_current_yaml(commit, repo_service)
        settings = read_yaml_field(current_yaml, ("coverage", "status"))

        status_set = False

        if settings and any(settings.values()):
            statuses = await repo_service.get_commit_statuses(commitid)
            url = make_url(repo_service, "commit", commitid)

            for context in ("project", "patch", "changes"):
                if settings.get(context):
                    for key, config in default_if_true(settings[context]):
                        try:
                            title = "codecov/%s%s" % (
                                context,
                                ("/" + key if key != "default" else ""),
                            )
                            assert match(
                                config.get("branches"), branch or ""
                            ), "Ignore setting pending status on branch"
                            assert (
                                on_a_pull_request
                                if config.get("only_pulls", False)
                                else True
                            ), "Set pending only on pulls"
                            assert config.get(
                                "set_pending", True
                            ), "Pending status disabled in YAML"
                            assert title not in statuses, "Pending status already set"

                            await repo_service.set_commit_status(
                                commit=commitid,
                                status="pending",
                                context=title,
                                description="Collecting reports and waiting for CI to complete",
                                url=url,
                            )
                            status_set = True
                            log.info(
                                "Status set", extra=dict(context=title, state="pending")
                            )
                        except AssertionError as e:
                            log.warning(str(e), extra=dict(context=context))

        return {"status_set": status_set}


RegisteredStatusSetPendingTask = celery_app.register_task(StatusSetPendingTask())
status_set_pending_task = celery_app.tasks[StatusSetPendingTask.name]
