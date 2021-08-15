import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, Sequence, Tuple

from shared.storage.exceptions import FileNotInStorageError
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.profiling import ProfilingCommit, ProfilingUpload
from helpers.clock import get_utc_now
from services.archive import ArchiveService
from services.redis import get_redis_connection
from tasks.base import BaseCodecovTask
from tasks.profiling_summarization import profiling_summarization_task

log = logging.getLogger(__name__)


class ProfilingCollectionTask(BaseCodecovTask):

    name = "app.tasks.profilingsummarizationtask"

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
            profiling.last_joined_uploads_at = new_last_joined_at
            joined_execution_counts = self.join_profiling_uploads(
                profiling, new_profiling_uploads_to_join
            )
            location = self.store_results(profiling, joined_execution_counts)
            task_id = profiling_summarization_task.delay(profiling_id=profiling_id)
            return {
                "successful": True,
                "location": location,
                "summarization_task_id": task_id,
            }

    def find_uploads_to_join(
        self, profiling: ProfilingCommit, before: datetime
    ) -> Tuple[Sequence[ProfilingUpload], datetime]:
        new_now = before
        db_session = profiling.get_db_session()
        new_profiling_uploads_to_join = db_session.query(ProfilingUpload).filter(
            ProfilingUpload.profiling_commit_id == profiling.id,
            ProfilingUpload.created_at <= new_now,
        )
        if profiling.last_joined_uploads_at is not None:
            new_profiling_uploads_to_join = new_profiling_uploads_to_join.filter(
                ProfilingUpload.created_at > profiling.last_joined_uploads_at
            )
        return (
            new_profiling_uploads_to_join.order_by(ProfilingUpload.created_at),
            new_now,
        )

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
        for upload in new_profiling_uploads_to_join:
            self.merge_into(archive_service, existing_results, upload)
        return existing_results

    def merge_into(self, archive_service, existing_results, upload):
        try:
            file_mapping = {
                data["filename"]: data for data in existing_results["files"]
            }
            upload_data = json.loads(
                archive_service.read_file(upload.raw_upload_location)
            )
            for single_file in upload_data["files"]:
                if single_file in file_mapping:
                    file_dict = file_mapping[single_file]
                else:
                    file_dict = {"filename": single_file, "ln_ex_ct": []}
                    existing_results["files"].append(file_dict)
                counter = Counter()
                for ln, ln_ct in file_dict["ln_ex_ct"]:
                    counter[ln] += ln_ct
                for ln, ln_ct in upload_data["files"][single_file].items():
                    counter[int(ln)] += ln_ct
                file_dict["ln_ex_ct"] = [(a, b) for (a, b) in counter.items()]
        except FileNotInStorageError:
            log.info(
                "Skipping profiling upload because we can't fetch it from storage",
                extra=dict(upload_id=upload.id),
            )

    def store_results(self, profiling, joined_execution_counts):
        archive_service = ArchiveService(profiling.repository)
        location = archive_service.write_profiling_collection_result(
            profiling.version_identifier, json.dumps(joined_execution_counts)
        )
        profiling.summarized_location = location
        return location


RegisteredProfilingCollectionTask = celery_app.register_task(ProfilingCollectionTask())
profiling_collection_task = celery_app.tasks[RegisteredProfilingCollectionTask.name]
