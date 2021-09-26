import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, Sequence, Tuple

from shared.celery_config import profiling_collection_task_name
from shared.storage.exceptions import FileNotInStorageError
from sqlalchemy.orm.session import Session
from sqlalchemy.sql.expression import func

from app import celery_app
from database.models.profiling import ProfilingCommit, ProfilingUpload
from helpers.clock import get_utc_now
from helpers.metrics import metrics
from services.archive import ArchiveService
from services.redis import get_redis_connection
from tasks.base import BaseCodecovTask
from tasks.profiling_summarization import profiling_summarization_task

log = logging.getLogger(__name__)


class ProfilingCollectionTask(BaseCodecovTask):

    name = profiling_collection_task_name

    async def run_async(
        self, db_session: Session, *, profiling_id: int, **kwargs,
    ):
        redis_connection = get_redis_connection()
        with redis_connection.lock(f"totalize_profilings_lock_{profiling_id}"):
            profiling = (
                db_session.query(ProfilingCommit).filter_by(id=profiling_id).first()
            )
            (
                new_profiling_uploads_to_join,
                new_last_joined_at,
            ) = self.find_uploads_to_join(
                profiling, get_utc_now() - timedelta(seconds=60)
            )
            log.info(
                "Joining profiling uploads into profiling commit",
                extra=dict(
                    profiling_id=profiling_id,
                    number_uploads=new_profiling_uploads_to_join.count(),
                    new_last_joined_at=new_last_joined_at.isoformat(),
                ),
            )
            joined_execution_counts = self.join_profiling_uploads(
                profiling, new_profiling_uploads_to_join
            )
            location = self.store_results(profiling, joined_execution_counts)
            profiling.last_joined_uploads_at = new_last_joined_at
            db_session.commit()
            task_id = profiling_summarization_task.delay(profiling_id=profiling_id).id
            return {
                "successful": True,
                "location": location,
                "summarization_task_id": task_id,
            }

    @metrics.timer("worker.internal.task.find_uploads_to_join")
    def find_uploads_to_join(
        self,
        profiling: ProfilingCommit,
        before: datetime,
        max_number_of_results: int = 500,
    ) -> Tuple[Sequence[ProfilingUpload], datetime]:
        new_now = before
        db_session = profiling.get_db_session()
        new_profiling_uploads_to_join = db_session.query(ProfilingUpload).filter(
            ProfilingUpload.profiling_commit_id == profiling.id,
            ProfilingUpload.normalized_at <= new_now,
        )
        if profiling.last_joined_uploads_at is not None:
            new_profiling_uploads_to_join = new_profiling_uploads_to_join.filter(
                ProfilingUpload.normalized_at > profiling.last_joined_uploads_at
            )
        new_profiling_uploads_to_join = new_profiling_uploads_to_join.order_by(
            ProfilingUpload.normalized_at
        )
        latest_upload_time = (
            db_session.query(func.max(ProfilingUpload.normalized_at))
            .filter(
                ProfilingUpload.id.in_(
                    new_profiling_uploads_to_join.with_entities(
                        ProfilingUpload.id
                    ).limit(max_number_of_results)
                )
            )
            .first()
        )[0]
        if latest_upload_time:
            new_now = latest_upload_time
            new_profiling_uploads_to_join = new_profiling_uploads_to_join.filter(
                ProfilingUpload.normalized_at <= latest_upload_time
            ).order_by(ProfilingUpload.normalized_at)
        return (
            new_profiling_uploads_to_join,
            new_now,
        )

    @metrics.timer("worker.internal.task.join_profiling_uploads")
    def join_profiling_uploads(
        self, profiling: "ProfilingCommit", new_profiling_uploads_to_join
    ) -> Dict:
        archive_service = ArchiveService(profiling.repository)
        if profiling.joined_location:
            existing_results = json.loads(
                archive_service.read_file(profiling.joined_location)
            )
        else:
            existing_results = {"metadata": {"version": "v1"}, "files": []}
        self.merge_into(
            archive_service, existing_results, new_profiling_uploads_to_join
        )
        return existing_results

    def merge_into(
        self, archive_service, existing_results, new_profiling_uploads_to_join
    ):
        counters = defaultdict(Counter)
        for upload in new_profiling_uploads_to_join:
            try:
                upload_data = json.loads(
                    archive_service.read_file(upload.normalized_location)
                )
            except FileNotInStorageError:
                log.info(
                    "Skipping profiling upload because we can't fetch it from storage",
                    extra=dict(upload_id=upload.id),
                )
            else:
                file_mapping = {
                    data["filename"]: data for data in existing_results["files"]
                }
                for run in upload_data["runs"]:
                    for single_file in run["execs"]:
                        filename = single_file["filename"]
                        for ln, ln_ct in single_file["lines"].items():
                            counters[filename][int(ln)] += ln_ct
        with metrics.timer("worker.internal.task.merge_into"):
            for filename, file_counter in counters.items():
                if filename in file_mapping:
                    file_dict = file_mapping[filename]
                else:
                    file_dict = {"filename": filename, "ln_ex_ct": []}
                    existing_results["files"].append(file_dict)
                for ln, ln_ct in file_dict["ln_ex_ct"]:
                    file_counter[ln] += ln_ct
                file_dict["ln_ex_ct"] = [
                    (a, b) for (a, b) in sorted(file_counter.items())
                ]

    def store_results(self, profiling, joined_execution_counts) -> str:
        archive_service = ArchiveService(profiling.repository)
        location = archive_service.write_profiling_collection_result(
            profiling.version_identifier, json.dumps(joined_execution_counts)
        )
        profiling.joined_location = location
        return location


RegisteredProfilingCollectionTask = celery_app.register_task(ProfilingCollectionTask())
profiling_collection_task = celery_app.tasks[RegisteredProfilingCollectionTask.name]
