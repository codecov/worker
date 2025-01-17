import datetime as dt

from redis.exceptions import LockError
from shared.config import get_config
from shared.django_apps.test_analytics.models import LastRollupDate
from shared.utils.enums import TaskConfigGroup
from sqlalchemy.orm import Session

from app import celery_app
from django_scaffold import settings
from services.redis import get_redis_connection
from ta_storage.bq import BQDriver
from ta_storage.pg import PGDriver
from tasks.base import BaseCodecovTask

ta_cache_analytics_task_name = (
    f"app.tasks.{TaskConfigGroup.cache_rollup.value}.TACacheAnalyticsTask"
)


class TACacheAnalyticsTask(BaseCodecovTask, name=ta_cache_analytics_task_name):
    def run_impl(
        self,
        db_session: Session,
        repoid: int,
        branch: str,
        update_date: bool = True,
        **kwargs,
    ):
        redis_conn = get_redis_connection()
        try:
            with redis_conn.lock(
                f"rollups:{repoid}:{branch}", timeout=300, blocking_timeout=2
            ):
                self.run_impl_within_lock(db_session, repoid, branch)

                if update_date:
                    LastRollupDate.objects.update_or_create(
                        repoid=repoid,
                        branch=branch,
                        defaults={"last_rollup_date": dt.date.today()},
                    )

            with redis_conn.lock(f"rollups:{repoid}", timeout=300, blocking_timeout=2):
                self.run_impl_within_lock(db_session, repoid, None)

                if update_date:
                    LastRollupDate.objects.update_or_create(
                        repoid=repoid,
                        branch=None,
                        defaults={"last_rollup_date": dt.date.today()},
                    )

        except LockError:
            return {"in_progress": True}

        return {"success": True}

    def run_impl_within_lock(
        self, db_session: Session, repoid: int, branch: str | None
    ):
        write_buckets = get_config(
            "services", "test_analytics", "write_buckets", default=None
        )

        buckets = write_buckets or [
            get_config("services", "minio", "bucket", default="codecov")
        ]

        if settings.BIGQUERY_WRITE_ENABLED:
            bq = BQDriver(repo_id=repoid)
            bq.cache_analytics(buckets, branch)

        pg = PGDriver(
            repoid,
        )
        pg.cache_analytics(buckets, branch)


RegisteredTACacheAnalyticsTask = celery_app.register_task(TACacheAnalyticsTask())
ta_cache_analytics_task = celery_app.tasks[RegisteredTACacheAnalyticsTask.name]
