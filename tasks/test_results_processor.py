import base64
import json
import logging
import random
import zlib
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from json import loads
from typing import List

from redis.exceptions import LockError
from shared.celery_config import test_results_processor_task_name
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.orm import Session
from testing_result_parsers import (
    Testrun,
    parse_junit_xml,
    parse_pytest_reportlog,
    parse_vitest_json,
)

from app import celery_app
from database.models import Repository, Upload
from database.models.reports import Test, TestInstance
from services.archive import ArchiveService
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class TestResultsProcessorTask(BaseCodecovTask, name=test_results_processor_task_name):
    __test__ = False

    async def run_async(
        self,
        db_session,
        *,
        repoid,
        commitid,
        commit_yaml,
        arguments_list,
        report_code=None,
        **kwargs,
    ):
        commit_yaml = UserYaml(commit_yaml)

        repoid = int(repoid)
        log.info(
            "Received upload test result processing task",
            extra=dict(repoid=repoid, commit=commitid),
        )

        testrun_list = []
        upload_list = []

        # process each report session's test information
        for args in arguments_list:
            upload_obj: Upload = (
                db_session.query(Upload).filter_by(id_=args.get("upload_pk")).first()
            )

            try:
                parsed_testruns: List[Testrun] = self.process_individual_arg(
                    upload_obj, upload_obj.report.commit.repository
                )
            except Exception:
                log.warning(f"Error parsing testruns")
                return {"successful": False}

            # concat existing and new test information
            testrun_list += parsed_testruns

            upload_list.append(upload_obj)

        # save relevant stuff to database
        self.save_report(db_session, testrun_list, upload_obj)

        # kick off notification task stuff

        if self.should_delete_archive(commit_yaml):
            repository = (
                db_session.query(Repository)
                .filter(Repository.repoid == int(repoid))
                .first()
            )
            self.delete_archive(
                commitid, repository, commit_yaml, uploads_to_delete=upload_list
            )

        return {
            "successful": True,
            "testrun_list": [self.testrun_to_dict(t) for t in testrun_list],
        }

    def save_report(
        self, db_session: Session, testrun_list: List[Testrun], upload: Upload
    ):
        for testrun in testrun_list:
            test = (
                db_session.query(Test)
                .filter_by(name=testrun.name, testsuite=testrun.testsuite)
                .first()
            )
            if not test:
                test = Test(
                    repoid=upload.report.commit.repoid,
                    name=testrun.name,
                    testsuite=testrun.testsuite,
                )
                db_session.add(test)
                db_session.flush()

            db_session.add(
                TestInstance(
                    test_id=test.id,
                    duration_seconds=testrun.duration,
                    outcome=int(testrun.outcome),
                    upload_id=upload.id,
                )
            )
            db_session.flush()

    def process_individual_arg(self, upload: Upload, repository) -> List[Testrun]:
        archive_service = ArchiveService(repository)

        payload_bytes = archive_service.read_file(upload.storage_path)
        data = json.loads(payload_bytes)

        testrun_list = []

        for file in data["test_results_files"]:
            file = file["data"]
            print(file)
            file_bytes = BytesIO(zlib.decompress(base64.b64decode(file)))
            print(file_bytes)

            first_line = file_bytes.readline()
            file_bytes.seek(0)

            file_content = file_bytes.read()

            # TODO: improve report matching capabilities
            # use file extensions?
            # maybe do the matching in the testing result parser lib?
            try:
                if first_line.startswith(b"<?xml"):
                    testrun_list = parse_junit_xml(file_content)
                elif b"pytest" in first_line:
                    testrun_list = parse_pytest_reportlog(file_content)
                else:
                    testrun_list = parse_vitest_json(file_content)
            except Exception:
                log.warning(f"Error parsing: {file_content.decode()}")

        return testrun_list

    def testrun_to_dict(self, t: Testrun):
        return {
            "outcome": str(t.outcome),
            "name": t.name,
            "testsuite": t.testsuite,
            "duration_seconds": t.duration,
        }

    def should_delete_archive(self, commit_yaml):
        if get_config("services", "minio", "expire_raw_after_n_days"):
            return True
        return not read_yaml_field(
            commit_yaml, ("codecov", "archive", "uploads"), _else=True
        )

    def delete_archive(
        self, commitid, repository, commit_yaml, uploads_to_delete: List[Upload]
    ):
        if self.should_delete_archive(commit_yaml):
            archive_service = ArchiveService(repository)
            for upload in uploads_to_delete:
                archive_url = upload.storage_path
                if archive_url and not archive_url.startswith("http"):
                    log.info(
                        "Deleting uploaded file as requested",
                        extra=dict(
                            archive_url=archive_url,
                            commit=commitid,
                            upload=upload.external_id,
                            parent_task=self.request.parent_id,
                        ),
                    )
                    archive_service.delete_file(archive_url)
            return True

        return False


RegisteredTestResultsProcessorTask = celery_app.register_task(
    TestResultsProcessorTask()
)
test_results_processor_task = celery_app.tasks[RegisteredTestResultsProcessorTask.name]
