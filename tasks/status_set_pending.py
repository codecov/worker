import logging

from app import celery_app
from celery_config import status_set_pending_task_name
from covreportgs.helpers.yaml import walk
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StatusSetPendingTask(BaseCodecovTask):
    """
    """
    name = status_set_pending_task_name

    async def run_async(self, db_session, repoid, commitid, branch, on_a_pull_request, *args, **kwargs):
        log.info(
            'Set pending',
            extra=dict(repoid=repoid, commitid=commitid, branch=branch, on_a_pull_request=on_a_pull_request)
        )

        # TODO: need to check for enterprise license
        # assert license.LICENSE['valid'], ('Notifications disabled. '+(license.LICENSE['warning'] or ''))

        # TODO: still in beta?
        # if not self.redis.sismember('beta.pending', repoid):
        #     raise gen.Return('Pending disabled. Please request to be in beta.')

        # TODO: get repo

        settings = walk(self.repository.data['yaml'], ('coverage', 'status'))
        if settings and any(settings.values()):
            statuses = yield self.repository.get_commit_statuses(commitid)
            url = make_url(self.repository, 'commit', commitid)

            for context in ('project', 'patch', 'changes'):
                if settings.get(context):
                    for key, config in default_if_true(settings[context]):
                        try:
                            title = 'codecov/%s%s' % (context, ('/'+key if key != 'default' else ''))
                            assert match(config.get('branches'), branch), 'Ignore setting pending status on branch'
                            assert on_a_pull_request if config.get('only_pulls', False) else True, 'Set pending only on pulls'
                            assert config.get('set_pending', True), 'Pending status disabled in YAML'
                            assert title not in statuses, 'Pending status already set'

                            yield self.repository.set_commit_status(commit=commitid,
                                                                    status='pending',
                                                                    context=title,
                                                                    description='Collecting reports and waiting for CI to complete',
                                                                    url=url)
                            self.log(
                                'info',
                                'Status set',
                                context=title,
                                state='pending'
                            )
                        except AssertionError as e:
                            self.log('warn', str(e), context=context)

RegisteredStatusSetPendingTask = celery_app.register_task(StatusSetPendingTask())
status_set_pending_task = celery_app.tasks[StatusSetPendingTask.name]
