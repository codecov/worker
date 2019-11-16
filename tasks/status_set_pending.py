import logging
import re

from app import celery_app
from celery_config import status_set_pending_task_name
from covreports.helpers.yaml import walk
from services.repository import get_repo
from covreports.config import get_config
from covreports.utils.match import match
from covreports.utils.urls import make_url
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StatusSetPendingTask(BaseCodecovTask):
    """
    Sets commit status to pending
    """
    name = status_set_pending_task_name

    async def run_async(self, db_session, repoid, commitid, branch, on_a_pull_request, *args, **kwargs):
        log.info(
            'Set pending',
            extra=dict(repoid=repoid, commitid=commitid, branch=branch, on_a_pull_request=on_a_pull_request)
        )

        # TODO: need to check for enterprise license?
        # assert license.LICENSE['valid'], ('Notifications disabled. '+(license.LICENSE['warning'] or ''))

        # TODO: still in beta?
        # if not self.redis.sismember('beta.pending', repoid):
        #     raise gen.Return('Pending disabled. Please request to be in beta.')

        repo = await get_repo(db_session, repoid, commitid)

        settings = walk(repo.data['yaml'], ('coverage', 'status'))
        if settings and any(settings.values()):
            statuses = await repo.get_commit_statuses(commitid)
            url = make_url(repo, 'commit', commitid)

            for context in ('project', 'patch', 'changes'):
                if settings.get(context):
                    for key, config in self.default_if_true(settings[context]):
                        try:
                            title = 'codecov/%s%s' % (context, ('/'+key if key != 'default' else ''))
                            assert match(config.get('branches'), branch or ''), 'Ignore setting pending status on branch'
                            assert on_a_pull_request if config.get('only_pulls', False) else True, 'Set pending only on pulls'
                            assert config.get('set_pending', True), 'Pending status disabled in YAML'
                            assert title not in statuses, 'Pending status already set'

                            await repo.set_commit_status(commit=commitid,
                                                         status='pending',
                                                         context=title,
                                                         description='Collecting reports and waiting for CI to complete',
                                                         url=url)
                            log.info(
                                'Status set',
                                extra=dict(context=title, state='pending')
                            )
                        except AssertionError as e:
                            log.warn(
                                str(e),
                                extra=dict(context=context)
                            )

    # TODO: factor out? - this will be used by set_pending and set_error
    def default_if_true(self, value):
        if value is True:
            yield 'default', {}
        elif type(value) is dict:
            for key, data in value.items():
                if data is False:
                    continue
                elif data is True:
                    yield key, {}
                elif type(data) is not dict or data.get('enabled') is False:
                    continue
                else:
                    yield key, data

RegisteredStatusSetPendingTask = celery_app.register_task(StatusSetPendingTask())
status_set_pending_task = celery_app.tasks[StatusSetPendingTask.name]
