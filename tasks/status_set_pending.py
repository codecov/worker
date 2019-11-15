import logging
import re

from app import celery_app
from celery_config import status_set_pending_task_name
from covreports.helpers.yaml import walk
from services.repository import get_repo
from covreports.config import get_config
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

# TODO: move to shared lib
from tornado.escape import url_escape
from tornado.httputil import url_concat

def escape(string, _url_escape=False):
    if isinstance(string, str):
        if _url_escape:
            return url_escape(string).replace('%2F', '/')
        else:
            return string.encode('utf-8', 'replace')
    elif _url_escape:
        return str(string)
    else:
        return string

# TODO: move to shared lib
services_short = dict(github='gh',
                      github_enterprise='ghe',
                      bitbucket='bb',
                      bitbucket_server='bbs',
                      gitlab='gl',
                      gitlab_enterprise='gle')
def make_url(repository, *args, **kwargs):
    args = list(map(lambda a: escape(a, True), list(args)))
    kwargs = dict([(k, escape(v)) for k, v in kwargs.items() if v is not None])
    if repository:
        return url_concat('/'.join([get_config('setup', 'codecov_url'),
                                    services_short[repository.service],
                                    repository.slug] + args),
                          kwargs)
    else:
        return url_concat('/'.join([get_config('setup', 'codecov_url')] + args),
                          kwargs)


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
                            assert self.match(config.get('branches'), branch or ''), 'Ignore setting pending status on branch'
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

    # TODO: factor out?
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

    # TODO: factor out?
    def match(self, patterns, string):
        if patterns is None or string in patterns:
            return True

        patterns = set(filter(None, patterns))
        negatives = filter(lambda a: a.startswith(('^!', '!')), patterns)
        positives = patterns - set(negatives)

        # must not match
        for pattern in negatives:
            # matched a negative search
            if re.match(pattern.replace('!', ''), string):
                return False

        if positives:
            for pattern in positives:
                # match was found
                if re.match(pattern, string):
                    return True

            # did not match any required paths
            return False

        else:
            # no positives: everyting else is ok
            return True

RegisteredStatusSetPendingTask = celery_app.register_task(StatusSetPendingTask())
status_set_pending_task = celery_app.tasks[StatusSetPendingTask.name]
