import logging
from typing import Any

import sentry_sdk
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.orm import Session
from test_results_parser import parse_raw_upload

from app import celery_app
from database.models import (
    Commit,
    Repository,
    Upload,
)
from services.archive import ArchiveService
from services.processing.types import UploadArguments
from services.test_results import get_flake_set
from services.yaml import read_yaml_field
from ta_storage.bq import BQDriver
from ta_storage.pg import PGDriver
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
        successful = False

        commit = db_session.query(Commit).filter_by(commitid=commitid).first()
        branch = commit.branch

        # process each report session's test information
        upload = db_session.query(Upload).filter_by(id_=argument["upload_id"]).first()
        result = self.process_individual_upload(
            db_session,
            archive_service,
            repoid,
            commitid,
            branch,
            upload,
            should_delete_archive,
        )
        if result:
            successful = True

        return successful

    def process_individual_upload(
        self,
        db_session,
        archive_service: ArchiveService,
        repoid: int,
        commitid: str,
        branch: str,
        upload: Upload,
        should_delete_archive: bool,
    ) -> bool:
        upload_id = upload.id

        log.info("Processing individual upload", extra=dict(upload_id=upload_id))
        if upload.state == "v2_processed":
            # don't need to process again because the intermediate result should already be in redis
            return False

        payload_bytes = archive_service.read_file(upload.storage_path)

        try:
            parsing_infos, readable_file = parse_raw_upload(payload_bytes)
        except RuntimeError as exc:
            log.error(
                "Error parsing raw test results upload",
                extra=dict(
                    repoid=upload.report.commit.repoid,
                    commitid=upload.report.commit_id,
                    uploadid=upload.id,
                    parser_err_msg=str(exc),
                ),
            )
            sentry_sdk.capture_exception(exc, tags={"upload_state": upload.state})
            upload.state = "v2_processed"
            db_session.commit()
            return False
        else:
            flaky_test_set = get_flake_set(db_session, upload.report.commit.repoid)
            pg = PGDriver(db_session, flaky_test_set)
            bq = BQDriver()

            for parsing_info in parsing_infos:
                framework = parsing_info["framework"]
                testruns = parsing_info["testruns"]
                pg.write_testruns(
                    None,
                    repoid,
                    commitid,
                    branch,
                    upload,
                    framework,
                    testruns,
                )

                bq.write_testruns(
                    None,
                    repoid,
                    commitid,
                    branch,
                    upload,
                    framework,
                    testruns,
                )

            upload.state = "v2_processed"
            db_session.commit()

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
