import logging
from typing import Any

import sentry_sdk
from redis import Redis
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.orm import Session
from test_results_parser import ParserError, parse_raw_upload

from app import celery_app
from database.models import (
    Repository,
    Upload,
)
from services.archive import ArchiveService
from services.processing.types import UploadArguments
from services.redis import get_redis_connection
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)

ta_processor_task_name = "app.tasks.test_results.TAProcessor"


class TAProcessorTask(BaseCodecovTask, name=ta_processor_task_name):
    __test__ = False

    def run_impl(
        self,
        db_session: Session,
        *args,
        repoid: int,
        commitid: str,
        commit_yaml: dict[str, Any],
        argument: UploadArguments,
        **kwargs,
    ) -> bool:
        log.info("Received TA processing task")

        user_yaml: UserYaml = UserYaml(commit_yaml)
        repoid = int(repoid)

        repository = (
            db_session.query(Repository)
            .filter(Repository.repoid == int(repoid))
            .first()
        )

        should_delete_archive = self.should_delete_archive(user_yaml)
        archive_service = ArchiveService(repository)

        redis_client = get_redis_connection()

        successful = False

        # process each report session's test information
        upload = db_session.query(Upload).filter_by(id_=argument["upload_id"]).first()
        result = self.process_individual_upload(
            db_session,
            redis_client,
            archive_service,
            repository,
            commitid,
            upload,
            should_delete_archive,
        )
        if result:
            successful = True

        return successful

    def process_individual_upload(
        self,
        db_session,
        redis_client: Redis,
        archive_service: ArchiveService,
        repository: Repository,
        commitid,
        upload: Upload,
        should_delete_archive: bool,
    ) -> bool:
        upload_id = upload.id

        log.info("Processing individual upload", extra=dict(upload_id=upload_id))
        if upload.state == "v2_processed" or upload.state == "v2_failed":
            return False

        payload_bytes = archive_service.read_file(upload.storage_path)

        try:
            msgpacked, readable_file = parse_raw_upload(payload_bytes)
        except ParserError as exc:
            log.error(
                "Error parsing file",
                extra=dict(
                    repoid=upload.report.commit.repoid,
                    commitid=upload.report.commit_id,
                    uploadid=upload.id,
                    parser_err_msg=str(exc),
                ),
            )
            sentry_sdk.capture_exception(exc, tags={"upload_state": upload.state})
            upload.state = "v2_failed"
            db_session.commit()
            return False
        else:
            redis_client.set(
                f"ta/intermediate/{repository.repoid}/{commitid}/{upload_id}",
                bytes(msgpacked),
                ex=60 * 60,
            )

            upload.state = "v2_processed"
            db_session.commit()

            log.info(
                "Finished processing individual upload", extra=dict(upload_id=upload_id)
            )

            if should_delete_archive:
                self.delete_archive(archive_service, upload)
            else:
                archive_service.write_file(upload.storage_path, bytes(readable_file))

        return True

    def should_delete_archive(self, user_yaml: UserYaml):
        if get_config("services", "minio", "expire_raw_after_n_days"):
            return True
        return not read_yaml_field(
            user_yaml, ("codecov", "archive", "uploads"), _else=True
        )

    def delete_archive(self, archive_service: ArchiveService, upload: Upload):
        archive_url = upload.storage_path
        if archive_url and not archive_url.startswith("http"):
            log.info(
                "Deleting uploaded file as requested",
                extra=dict(
                    archive_url=archive_url,
                    upload=upload.external_id,
                ),
            )
            archive_service.delete_file(archive_url)


RegisteredTAProcessorTask = celery_app.register_task(TAProcessorTask())
ta_processor_task = celery_app.tasks[RegisteredTAProcessorTask.name]
