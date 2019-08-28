# http://docs.celeryq.org/en/latest/configuration.html#configuration
import logging

import logging.config

from helpers.logging_config import get_logging_config_dict

from helpers.config import get_config
from celery import signals

log = logging.getLogger(__name__)


@signals.setup_logging.connect
def initialize_logging(loglevel=logging.INFO, **kwargs):
    config_dict = get_logging_config_dict()
    logging.config.dictConfig(config_dict)
    celery_logger = logging.getLogger('celery')
    celery_logger.setLevel(loglevel)
    log.info("Initialized celery logging")
    return celery_logger


broker_url = get_config('services', 'redis_url'),
result_backend = get_config('services', 'redis_url')

task_default_queue = 'new_tasks'

# Import jobs
imports = ('tasks', )

task_serializer = 'json'

accept_content = ['json']

# http://docs.celeryproject.org/en/latest/configuration.html?highlight=celery_redirect_stdouts#celeryd-hijack-root-logger
worker_hijack_root_logger = False

timezone = 'UTC'
enable_utc = True

# http://docs.celeryproject.org/en/latest/configuration.html#celery-ignore-result
task_ignore_result = True

# http://celery.readthedocs.org/en/latest/userguide/tasks.html#disable-rate-limits-if-they-re-not-used
worker_disable_rate_limits = True

# http://celery.readthedocs.org/en/latest/faq.html#should-i-use-retry-or-acks-late
task_acks_late = bool(get_config('setup', 'tasks', 'celery', 'acks_late'))

# http://celery.readthedocs.org/en/latest/userguide/optimizing.html#prefetch-limits
worker_prefetch_multiplier = int(get_config('setup', 'tasks', 'celery', 'prefetch', default=4))
# !!! NEVER 0 !!! 0 == infinate

# http://celery.readthedocs.org/en/latest/configuration.html#celeryd-task-soft-time-limit
task_soft_time_limit = int(get_config('setup', 'tasks', 'celery', 'soft_timelimit', default=400))

# http://celery.readthedocs.org/en/latest/configuration.html#std:setting-CELERYD_TASK_TIME_LIMIT
task_time_limit = int(get_config('setup', 'tasks', 'celery', 'hard_timelimit', default=480))

_default_queue = get_config('setup', 'tasks', 'celery', 'default_queue', default='celery')

refresh_task_name = 'app.tasks.refresh.Refresh'
notify_task_name = 'app.tasks.notify.Notify'
pulls_task_name = 'app.tasks.pulls.Sync'
status_set_error_task_name = 'app.tasks.status.SetError'
status_set_pending_task_name = 'app.tasks.status.SetPending'
upload_task_name = 'app.tasks.upload.Upload'
archive_task_name = 'app.tasks.archive.MigrateToArchive'
bot_task_name = 'app.tasks.bot.VerifyBot'
comment_task_name = 'app.tasks.comment.Comment'
flush_repo_task_name = 'app.tasks.flush_repo.FlushRepo'
github_marketplace_task_name = 'app.tasks.github_marketplace.SyncPlans'
remove_webhook_task_name = 'app.tasks.remove_webhook.RemoveOldHook'
synchronize_task_name = 'app.tasks.synchronize.Synchronize'


task_routes = {
    refresh_task_name: {
        'queue': get_config('setup', 'tasks', 'refresh', 'queue', default=_default_queue)
    },
    notify_task_name: {
        'queue': get_config('setup', 'tasks', 'notify', 'queue', default=_default_queue),
        'soft_time_limit': 15,
        'time_limit': 20
    },
    pulls_task_name: {
        'queue': get_config('setup', 'tasks', 'pulls', 'queue', default=_default_queue)
    },
    status_set_error_task_name: {
        'queue': get_config('setup', 'tasks', 'status', 'queue', default=_default_queue)
    },
    status_set_pending_task_name: {
        'queue': get_config('setup', 'tasks', 'status', 'queue', default=_default_queue)
    },
    upload_task_name: {
        'queue': get_config('setup', 'tasks', 'upload', 'queue', default=_default_queue)
    },
    archive_task_name: {
        'queue': get_config('setup', 'tasks', 'archive', 'queue', default=_default_queue)
    },
    bot_task_name: {
        'queue': get_config('setup', 'tasks', 'verify_bot', 'queue', default=_default_queue)
    },
    comment_task_name: {
        'queue': get_config('setup', 'tasks', 'comment', 'queue', default=_default_queue)
    },
    flush_repo_task_name: {
        'queue': get_config('setup', 'tasks', 'flush_repo', 'queue', default=_default_queue)
    },
    github_marketplace_task_name: {
        'queue': get_config('setup', 'tasks', 'sync_plans', 'queue', default=_default_queue)
    },
    remove_webhook_task_name: {
        'queue': get_config('setup', 'tasks', 'remove_webhook', 'queue', default=_default_queue)
    },
    synchronize_task_name: {
        'queue': get_config('setup', 'tasks', 'synchronize', 'queue', default=_default_queue)
    }
}
