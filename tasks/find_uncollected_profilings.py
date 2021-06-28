from datetime import timedelta

from tasks.crontasks import CodecovCronTask
from tasks.profiling_collection import profiling_collection_task

from database.models.profiling import ProfilingCommit, ProfilingUpload
from celery_config import find_uncollected_profilings_task_name
from sqlalchemy import func
from app import celery_app
from helpers.clock import get_utc_now


class FindUncollectedProfilingsTask(CodecovCronTask):

    name = find_uncollected_profilings_task_name

    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 3300

    async def run_cron_task(self, db_session, *args, **kwargs):
        min_interval_profilings = timedelta(hours=12)
        now = get_utc_now()
        query = (
            db_session.query(ProfilingCommit.id, func.count())
            .join(
                ProfilingUpload,
                ProfilingUpload.profiling_commit_id == ProfilingCommit.id,
            )
            .filter(
                (
                    ProfilingCommit.last_joined_uploads_at.is_(None)
                    & (ProfilingCommit.created_at <= now - min_interval_profilings)
                )
                | (
                    (
                        ProfilingCommit.last_joined_uploads_at
                        < ProfilingUpload.created_at
                    )
                    & (
                        ProfilingCommit.last_joined_uploads_at
                        <= now - min_interval_profilings
                    )
                )
            )
            .group_by(ProfilingCommit.id)
        )
        delayed_pids = []
        for pid, count in query:
            res = profiling_collection_task.delay(pid)
            delayed_pids.append((pid, count, res.as_tuple()))
        return {
            "delayed_profiling_ids": delayed_pids[:100],
            "delayed_profiling_ids_count": len(delayed_pids),
        }


RegisteredFindUncollectedProfilingsTask = celery_app.register_task(
    FindUncollectedProfilingsTask()
)
find_untotalized_profilings_task = celery_app.tasks[
    RegisteredFindUncollectedProfilingsTask.name
]
