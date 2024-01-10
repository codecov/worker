import base64
import json
import logging
import zlib
from io import BytesIO
from json import loads
from typing import List

from shared.celery_config import test_results_processor_task_name
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_results_parser import (
    ParserError,
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


class ParserFailureError(Exception):
    ...


class ParserNotSupportedError(Exception):
    ...


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
            except ParserFailureError:
                log.warning(
                    f"Error parsing testruns",
                    extra=dict(
                        repoid=repoid, commitid=commitid, uploadid=upload_obj.id
                    ),
                )
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
        repo_tests = (
            db_session.query(Test).filter_by(repoid=upload.report.commit.repoid).all()
        )
        # Issue here is that the test result processing tasks are running in parallel
        # The idea is that we can first get a list of existing tests from the database
        # if a test is not found in that list we try to insert it has already inserted the test
        # so we should just fetch it

        # however, this may cause significant performance issues the first time a user runs test
        # result ingestion on a large project

        test_dict = dict()
        for test in repo_tests:
            test_dict[f"{test.testsuite}::{test.name}"] = test
        for testrun in testrun_list:
            test = test_dict.get(f"{testrun.testsuite}::{testrun.name}", None)
            if not test:
                try:
                    test = Test(
                        repoid=upload.report.commit.repoid,
                        name=testrun.name,
                        testsuite=testrun.testsuite,
                    )
                    db_session.add(test)
                    db_session.commit()
                except IntegrityError:
                    db_session.rollback()
                    test = (
                        db_session.query(Test)
                        .filter_by(
                            repoid=upload.report.commit.repoid,
                            name=testrun.name,
                            testsuite=testrun.testsuite,
                        )
                        .first()
                    )

            db_session.add(
                TestInstance(
                    test_id=test.id,
                    duration_seconds=testrun.duration,
                    outcome=int(testrun.outcome),
                    upload_id=upload.id,
                    failure_message=testrun.failure_message,
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
            file_bytes = BytesIO(zlib.decompress(base64.b64decode(file)))

            try:
                parser, parsing_function = self.match_report(file_bytes)
            except ParserNotSupportedError:
                log.error(
                    "File did not match any parser format",
                    extra=dict(
                        file_content=file_bytes.read().decode()[:300],
                    ),
                )
                raise ParserFailureError()
            try:
                file_content = file_bytes.read()
                testrun_list += parsing_function(file_content)
            except ParserError as e:
                log.error(
                    "Error parsing test result file",
                    extra=dict(
                        file_content=file_content.decode()[:300],
                        parser=parser,
                        err_msg=str(e),
                    ),
                )
                raise ParserFailureError()

        return testrun_list

    def match_report(self, file_bytes):
        first_line = file_bytes.readline()
        second_line = file_bytes.readline()
        file_bytes.seek(0)
        first_line = self.remove_space_from_line(first_line)
        second_line = self.remove_space_from_line(second_line)
        first_two_lines = first_line + second_line

        parser = "no parser"
        if first_two_lines.startswith(b"<?xml"):
            parser = "junit_xml"
            parsing_function = parse_junit_xml
        elif first_two_lines.startswith(b'{"pytest_version":'):
            parser = "pytest_reportlog"
            parsing_function = parse_pytest_reportlog
        elif first_two_lines.startswith(b'{"numTotalTestSuites"'):
            parser = "vitest_json"
            parsing_function = parse_vitest_json
        else:
            raise ParserNotSupportedError()

        return parser, parsing_function

    def remove_space_from_line(self, line):
        return bytes("".join(line.decode("utf-8").split()), "utf-8")

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


RegisteredTestResultsProcessorTask = celery_app.register_task(
    TestResultsProcessorTask()
)
test_results_processor_task = celery_app.tasks[RegisteredTestResultsProcessorTask.name]
