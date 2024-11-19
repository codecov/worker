import datetime as dt
import logging

from shared.django_apps.reports.models import LastCacheRollupDate
from sqlalchemy.orm import Session

from app import celery_app
from celery_config import cache_rollup_cron_task_name
from tasks.cache_test_rollups import cache_test_rollups_task_name
from tasks.crontasks import CodecovCronTask

log = logging.getLogger(__name__)


class CacheRollupTask(CodecovCronTask, name=cache_rollup_cron_task_name):
    def run_cron_task(self, _db_session: Session, *args, **kwargs):
        # get repos that have not uploaded test results in the last 24 hours
        out_of_date_repo_branches = LastCacheRollupDate.objects.all()

        for repo_branch in out_of_date_repo_branches:
            repo = repo_branch.repository
            branch = repo_branch.branch

            if repo_branch.last_rollup_date < (dt.date.today() - dt.timedelta(days=30)):
                repo_branch.delete()
            else:
                self.app.tasks[cache_test_rollups_task_name].s(
                    repoid=repo.repoid,
                    branch=branch,
                    update_date=False,
                ).apply_async()


RegisteredCacheRollupTask = celery_app.register_task(CacheRollupTask())
cache_rollup_task = celery_app.tasks[RegisteredCacheRollupTask.name]
