# http://docs.celeryq.org/en/latest/configuration.html#configuration
import logging

import logging.config

from helpers.logging_config import get_logging_config_dict
from helpers.cache import cache, RedisBackend
from services.redis import get_redis_connection

from shared.config import get_config
from celery import signals

log = logging.getLogger(__name__)


@signals.setup_logging.connect
def initialize_logging(loglevel=logging.INFO, **kwargs):
    config_dict = get_logging_config_dict()
    logging.config.dictConfig(config_dict)
    celery_logger = logging.getLogger("celery")
    celery_logger.setLevel(loglevel)
    log.info("Initialized celery logging")
    return celery_logger


@signals.worker_process_init.connect
def initialize_cache(**kwargs):
    log.info("Initialized cache")
    redis_cache_backend = RedisBackend(get_redis_connection())
    cache.configure(redis_cache_backend)


broker_url = get_config("services", "celery_broker") or get_config(
    "services", "redis_url"
)
result_backend = get_config("services", "celery_broker") or get_config(
    "services", "redis_url"
)

result_backend_transport_options = {"visibility_timeout": 60 * 60 * 5}  # 5 hours

task_default_queue = get_config(
    "setup", "tasks", "celery", "default_queue", default="celery"
)

# Import jobs
imports = ("tasks",)

task_serializer = "json"

accept_content = ["json"]

worker_max_memory_per_child = 1500000  # 1.5GB

# http://docs.celeryproject.org/en/latest/configuration.html?highlight=celery_redirect_stdouts#celeryd-hijack-root-logger
worker_hijack_root_logger = False

timezone = "UTC"
enable_utc = True

# http://docs.celeryproject.org/en/latest/configuration.html#celery-ignore-result
task_ignore_result = True

# http://celery.readthedocs.org/en/latest/userguide/tasks.html#disable-rate-limits-if-they-re-not-used
worker_disable_rate_limits = True

# http://celery.readthedocs.org/en/latest/faq.html#should-i-use-retry-or-acks-late
task_acks_late = bool(get_config("setup", "tasks", "celery", "acks_late"))

# http://celery.readthedocs.org/en/latest/userguide/optimizing.html#prefetch-limits
worker_prefetch_multiplier = int(
    get_config("setup", "tasks", "celery", "prefetch", default=4)
)
# !!! NEVER 0 !!! 0 == infinate

# http://celery.readthedocs.org/en/latest/configuration.html#celeryd-task-soft-time-limit
task_soft_time_limit = int(
    get_config("setup", "tasks", "celery", "soft_timelimit", default=400)
)

# http://celery.readthedocs.org/en/latest/configuration.html#std:setting-CELERYD_TASK_TIME_LIMIT
task_time_limit = int(
    get_config("setup", "tasks", "celery", "hard_timelimit", default=480)
)

sync_teams_task_name = "app.tasks.sync_teams.SyncTeams"
sync_repos_task_name = "app.tasks.sync_repos.SyncRepos"
delete_owner_task_name = "app.tasks.delete_owner.DeleteOwner"
notify_task_name = "app.tasks.notify.Notify"
pulls_task_name = "app.tasks.pulls.Sync"
status_set_error_task_name = "app.tasks.status.SetError"
status_set_pending_task_name = "app.tasks.status.SetPending"
upload_task_name = "app.tasks.upload.Upload"
archive_task_name = "app.tasks.archive.MigrateToArchive"
bot_task_name = "app.tasks.bot.VerifyBot"
comment_task_name = "app.tasks.comment.Comment"
flush_repo_task_name = "app.tasks.flush_repo.FlushRepo"
ghm_sync_plans_task_name = "app.tasks.ghm_sync_plans.SyncPlans"
send_email_task_name = "app.tasks.send_email.SendEmail"
remove_webhook_task_name = "app.tasks.remove_webhook.RemoveOldHook"
synchronize_task_name = "app.tasks.synchronize.Synchronize"
new_user_activated_task_name = "app.tasks.new_user_activated.NewUserActivated"
add_to_sendgrid_list_task_name = "app.tasks.add_to_sendgrid_list.AddToSendgridList"

task_annotations = {notify_task_name: {"soft_time_limit": 45, "time_limit": 60,}}

task_routes = {
    sync_teams_task_name: {
        "queue": get_config(
            "setup", "tasks", "sync_teams", "queue", default=task_default_queue
        )
    },
    sync_repos_task_name: {
        "queue": get_config(
            "setup", "tasks", "sync_repos", "queue", default=task_default_queue
        )
    },
    delete_owner_task_name: {
        "queue": get_config(
            "setup", "tasks", "delete_owner", "queue", default=task_default_queue
        )
    },
    notify_task_name: {
        "queue": get_config(
            "setup", "tasks", "notify", "queue", default=task_default_queue
        ),
    },
    pulls_task_name: {
        "queue": get_config(
            "setup", "tasks", "pulls", "queue", default=task_default_queue
        )
    },
    status_set_error_task_name: {
        "queue": get_config(
            "setup", "tasks", "status", "queue", default=task_default_queue
        )
    },
    status_set_pending_task_name: {
        "queue": get_config(
            "setup", "tasks", "status", "queue", default=task_default_queue
        )
    },
    upload_task_name: {
        "queue": get_config(
            "setup", "tasks", "upload", "queue", default=task_default_queue
        )
    },
    archive_task_name: {
        "queue": get_config(
            "setup", "tasks", "archive", "queue", default=task_default_queue
        )
    },
    bot_task_name: {
        "queue": get_config(
            "setup", "tasks", "verify_bot", "queue", default=task_default_queue
        )
    },
    comment_task_name: {
        "queue": get_config(
            "setup", "tasks", "comment", "queue", default=task_default_queue
        )
    },
    flush_repo_task_name: {
        "queue": get_config(
            "setup", "tasks", "flush_repo", "queue", default=task_default_queue
        )
    },
    ghm_sync_plans_task_name: {
        "queue": get_config(
            "setup", "tasks", "sync_plans", "queue", default=task_default_queue
        )
    },
    remove_webhook_task_name: {
        "queue": get_config(
            "setup", "tasks", "remove_webhook", "queue", default=task_default_queue
        )
    },
    synchronize_task_name: {
        "queue": get_config(
            "setup", "tasks", "synchronize", "queue", default=task_default_queue
        )
    },
    new_user_activated_task_name: {
        "queue": get_config(
            "setup", "tasks", "new_user_activated", "queue", default=task_default_queue
        )
    },
    add_to_sendgrid_list_task_name: {"queue": task_default_queue},
}
