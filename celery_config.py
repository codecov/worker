# http://docs.celeryq.org/en/latest/configuration.html#configuration
import logging

import logging.config

from helpers.cache import cache, RedisBackend
from services.redis import get_redis_connection

from shared.celery_config import BaseCeleryConfig
from celery import signals

log = logging.getLogger(__name__)


@signals.setup_logging.connect
def initialize_logging(loglevel=logging.INFO, **kwargs):
    celery_logger = logging.getLogger("celery")
    celery_logger.setLevel(loglevel)
    log.info("Initialized celery logging")
    return celery_logger


@signals.worker_process_init.connect
def initialize_cache(**kwargs):
    log.info("Initialized cache")
    redis_cache_backend = RedisBackend(get_redis_connection())
    cache.configure(redis_cache_backend)


sync_teams_task_name = "app.tasks.sync_teams.SyncTeams"
sync_repos_task_name = "app.tasks.sync_repos.SyncRepos"
delete_owner_task_name = "app.tasks.delete_owner.DeleteOwner"
notify_task_name = "app.tasks.notify.Notify"
pulls_task_name = "app.tasks.pulls.Sync"
status_set_error_task_name = "app.tasks.status.SetError"
status_set_pending_task_name = "app.tasks.status.SetPending"
upload_task_name = "app.tasks.upload.Upload"
upload_processor_task_name = "app.tasks.upload_processor.UploadProcessorTask"
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


class CeleryWorkerConfig(BaseCeleryConfig):
    pass
