import base64
import json
import logging
import zlib
from io import BytesIO
from typing import List

from sentry_sdk import metrics
from shared.celery_config import test_results_processor_task_name
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.dialects.postgresql import insert
from test_results_parser import (
    ParserError,
    Testrun,
    parse_junit_xml,
    parse_pytest_reportlog,
    parse_vitest_json,
)

from app import celery_app
from database.models import Repository, Test, TestInstance, Upload
from services.archive import ArchiveService
from services.test_results import generate_flags_hash, generate_test_id
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ParserFailureError(Exception):
    def __init__(self, err_msg, file_content, parser="", parser_err_msg=""):
        self.err_msg = err_msg
        self.file_content = file_content
        self.parser = parser
        self.parser_err_msg = parser_err_msg


class ParserNotSupportedError(Exception):
    ...


class TestResultsProcessorTask(BaseCodecovTask, name=test_results_processor_task_name):
    __test__ = False

    def run_impl(
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

        testrun_dict_list = []
        upload_list = []

        # process each report session's test information
        with metrics.timing("test_results.processor"):
            for args in arguments_list:
                upload_obj: Upload = (
                    db_session.query(Upload)
                    .filter_by(id_=args.get("upload_pk"))
                    .first()
                )

                res = self.process_individual_upload(
                    db_session, repoid, commitid, upload_obj
                )

                # concat existing and new test information
                testrun_dict_list.append(res)

                upload_list.append(upload_obj)

        if self.should_delete_archive(commit_yaml):
            repository = (
                db_session.query(Repository)
                .filter(Repository.repoid == int(repoid))
                .first()
            )
            self.delete_archive(
                commitid, repository, commit_yaml, uploads_to_delete=upload_list
            )

        return testrun_dict_list

    def process_individual_upload(
        self, db_session, repoid, commitid, upload_obj: Upload
    ):
        upload_id = upload_obj.id
        with metrics.timing("test_results.processor.process_individual_arg"):
            parsed_testruns: List[Testrun] = self.process_individual_arg(
                upload_obj, upload_obj.report.commit.repository
            )
        if not parsed_testruns:
            log.error(
                "No test result files were successfully parsed for this upload",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    upload_id=upload_id,
                ),
            )
            return {
                "successful": False,
            }
        flags_hash = generate_flags_hash(upload_obj.flag_names)
        upload_id = upload_obj.id
        with metrics.timing("test_results.processor.write_to_db"):
            for testrun in parsed_testruns:
                name = testrun.name
                testsuite = testrun.testsuite
                outcome = str(testrun.outcome)
                duration_seconds = testrun.duration
                failure_message = testrun.failure_message
                test_id = generate_test_id(repoid, testsuite, name, flags_hash)
                insert_on_conflict_do_nothing = (
                    insert(Test.__table__)
                    .values(
                        id=test_id,
                        repoid=repoid,
                        name=name,
                        testsuite=testsuite,
                        flags_hash=flags_hash,
                    )
                    .on_conflict_do_nothing()
                )
                db_session.execute(insert_on_conflict_do_nothing)
                db_session.flush()

                ti = TestInstance(
                    test_id=test_id,
                    upload_id=upload_id,
                    duration_seconds=duration_seconds,
                    outcome=outcome,
                    failure_message=failure_message,
                )
                db_session.add(ti)
                db_session.flush()

        return {
            "successful": True,
        }

    def process_individual_arg(self, upload: Upload, repository) -> List[Testrun]:
        archive_service = ArchiveService(repository)

        payload_bytes = archive_service.read_file(upload.storage_path)
        data = json.loads(payload_bytes)

        testrun_list = []

        for file_dict in data["test_results_files"]:
            filename = file_dict["filename"]
            file = file_dict["data"]
            file_bytes = BytesIO(zlib.decompress(base64.b64decode(file)))
            try:
                testrun_list += self.parse_single_file(filename, file_bytes)
            except ParserFailureError as exc:
                log.error(
                    exc.err_msg,
                    extra=dict(
                        repoid=upload.report.commit.repoid,
                        commitid=upload.report.commit_id,
                        uploadid=upload.id,
                        file_content=exc.file_content,
                        parser=exc.parser,
                        parser_err_msg=exc.parser_err_msg,
                    ),
                )

        return testrun_list

    def parse_single_file(
        self,
        filename: str,
        file_bytes: BytesIO,
    ):

        try:
            with metrics.timing("test_results.processor.parser_matching"):
                parser, parsing_function = self.match_report(filename, file_bytes)
        except ParserNotSupportedError as e:
            metrics.incr(
                "test_results.processor.parsing",
                tags={"status": "failure", "reason": "match_report_failure"},
            )
            raise ParserFailureError(
                err_msg="File did not match any parser format",
                file_content=file_bytes.read().decode()[:300],
            ) from e

        try:
            file_content = file_bytes.read()
            with metrics.timing("test_results.processor.file_parsing"):
                res = parsing_function(file_content)
        except ParserError as e:
            # aware of cardinality issues with using a variable here in the reason field but
            # parser is defined by us and limited to the amount of different parsers we will
            # write, so I don't expect this to be a problem for us
            metrics.incr(
                "test_results.processor.parsing",
                tags={"status": "failure", "reason": f"failed_to_parse_{parser}"},
            )
            raise ParserFailureError(
                err_msg="Error parsing file",
                file_content=file_content.decode()[:300],
                parser=parser,
                parser_err_msg=str(e),
            ) from e
        metrics.incr(
            "test_results.processor.parsing",
            tags={"status": "success", "parser": parser},
        )

        return res

    def match_report(self, filename: str, file_bytes: BytesIO):
        first_line = file_bytes.readline()
        second_line = file_bytes.readline()
        file_bytes.seek(0)
        first_line = self.remove_space_from_line(first_line)
        second_line = self.remove_space_from_line(second_line)
        first_two_lines = first_line + second_line

        parser = "no parser"
        if filename.endswith(".xml") or first_two_lines.startswith(b"<?xml"):
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
