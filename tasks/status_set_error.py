import logging
import re

from app import celery_app
from celery_config import status_set_error_task_name
from covreports.helpers.yaml import walk, default_if_true
from services.repository import get_repo_provider_service_by_id
from covreports.utils.urls import make_url
from database.models import Repository
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StatusSetErrorTask(BaseCodecovTask):
    """
    Set commit status upon error
    """
    name = status_set_error_task_name

    async def run_async(self, db_session, repoid, commitid, *, message=None, **kwargs):
        log.info(
            'Set error',
            extra=dict(repoid=repoid, commitid=commitid, description=message)
        )

        # TODO: need to check for enterprise license once licences are implemented
        # assert license.LICENSE['valid'], ('Notifications disabled. '+(license.LICENSE['warning'] or ''))

        repo = get_repo_provider_service_by_id(db_session, repoid)

        settings = walk(repo.data['yaml'], ('coverage', 'status'))
        if settings and any(settings.values()):
            statuses = await repo.get_commit_statuses(commitid)
            url = make_url(repo, 'commit', commitid)
            for context in ('project', 'patch', 'changes'):
                if settings.get(context):
                    for key, data in default_if_true(settings[context]):
                        context = 'codecov/%s%s' % (context, ('/'+key if key != 'default' else ''))
                        state = 'success' if data.get('informational') else data.get('if_ci_failed', 'error')
                        message = message or 'Coverage not measured fully because CI failed'
                        if context in statuses:
                            await repo.set_commit_status(commit=commitid,
                                                         status=state,
                                                         context=context,
                                                         description=message,
                                                         url=url)

                            log.info(
                                'Status set',
                                extra=dict(context=context, description=message, state=state)
                            )

RegisteredStatusSetErrorTask = celery_app.register_task(StatusSetErrorTask())
status_set_error_task = celery_app.tasks[StatusSetErrorTask.name]
