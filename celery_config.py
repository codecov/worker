# http://docs.celeryq.org/en/latest/configuration.html#configuration

from app import config


BROKER_URL = config.get(('services', 'celery_broker'))

# Import jobs
CELERY_IMPORTS = ('app.tasks', )

CELERY_TASK_SERIALIZER = 'json'

CELERY_ACCEPT_CONTENT = ['json']

# http://docs.celeryproject.org/en/latest/configuration.html#celery-send-events
CELERY_SEND_EVENTS = False

# http://docs.celeryproject.org/en/latest/configuration.html?highlight=celery_redirect_stdouts#celeryd-hijack-root-logger
CELERYD_HIJACK_ROOT_LOGGER = False

CELERY_TIMEZONE = 'UTC'
CELERY_ENABLE_UTC = True

# http://docs.celeryproject.org/en/latest/configuration.html#celery-ignore-result
CELERY_IGNORE_RESULT = True

# http://celery.readthedocs.org/en/latest/userguide/tasks.html#disable-rate-limits-if-they-re-not-used
CELERY_DISABLE_RATE_LIMITS = True

# http://celery.readthedocs.org/en/latest/faq.html#should-i-use-retry-or-acks-late
CELERY_ACKS_LATE = bool(config.get(('setup', 'tasks', 'celery', 'acks_late')))

# http://celery.readthedocs.org/en/latest/userguide/optimizing.html#prefetch-limits
CELERYD_PREFETCH_MULTIPLIER = int(config.get(('setup', 'tasks', 'celery', 'prefetch'), 4))
# !!! NEVER 0 !!! 0 == infinate

# http://celery.readthedocs.org/en/latest/configuration.html#celeryd-task-soft-time-limit
CELERYD_TASK_SOFT_TIME_LIMIT = int(config.get(('setup', 'tasks', 'celery', 'soft_timelimit'), 400))

# http://celery.readthedocs.org/en/latest/configuration.html#std:setting-CELERYD_TASK_TIME_LIMIT
CELERYD_TASK_TIME_LIMIT = int(config.get(('setup', 'tasks', 'celery', 'hard_timelimit'), 480))

_default_queue = config.get(('setup', 'tasks', 'celery', 'default_queue'), 'celery')

CELERY_ROUTES = {
    'app.tasks.refresh.Refresh': {
        'queue': config.get(('setup', 'tasks', 'refresh', 'queue'), _default_queue)
    },
    'app.tasks.notify.Notify': {
        'queue': config.get(('setup', 'tasks', 'notify', 'queue'), _default_queue),
        'soft_time_limit': 15,
        'time_limit': 20
    },
    'app.tasks.pulls.Sync': {
        'queue': config.get(('setup', 'tasks', 'pulls', 'queue'), _default_queue)
    },
    'app.tasks.status.SetError': {
        'queue': config.get(('setup', 'tasks', 'status', 'queue'), _default_queue)
    },
    'app.tasks.status.SetPending': {
        'queue': config.get(('setup', 'tasks', 'status', 'queue'), _default_queue)
    },
    'app.tasks.upload.Upload': {
        'queue': config.get(('setup', 'tasks', 'upload', 'queue'), _default_queue)
    },
    'app.tasks.archive.MigrateToArchive': {
        'queue': config.get(('setup', 'tasks', 'archive', 'queue'), _default_queue)
    },
    'app.tasks.bot.VerifyBot': {
        'queue': config.get(('setup', 'tasks', 'verify_bot', 'queue'), _default_queue)
    },
    # 'app.tasks.codecov_yml.Synchronize': {
    #     'queue': config.get(('setup', 'tasks', 'synchronize', 'queue'), _default_queue)
    # },
    'app.tasks.comment.Comment': {
        'queue': config.get(('setup', 'tasks', 'comment', 'queue'), _default_queue)
    },
    'app.tasks.flush_repo.FlushRepo': {
        'queue': config.get(('setup', 'tasks', 'flush_repo', 'queue'), _default_queue)
    },
    'app.tasks.github_marketplace.SyncPlans': {
        'queue': config.get(('setup', 'tasks', 'sync_plans', 'queue'), _default_queue)
    },
    'app.tasks.remove_webhook.RemoveOldHook': {
        'queue': config.get(('setup', 'tasks', 'remove_webhook', 'queue'), _default_queue)
    },
    'app.tasks.synchronize.Synchronize': {
        'queue': config.get(('setup', 'tasks', 'synchronize', 'queue'), _default_queue)
    }
}
