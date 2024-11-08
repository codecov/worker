import base64
import json
import logging
import zlib
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from typing import List

from shared.celery_config import test_results_processor_task_name
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from test_results_parser import (
    Outcome,
    ParserError,
    ParsingInfo,
    parse_junit_xml,
)

from app import celery_app
from database.models import (
    DailyTestRollup,
    Flake,
    Repository,
    RepositoryFlag,
    Test,
    TestFlagBridge,
    TestInstance,
    Upload,
)
from helpers.metrics import metrics
from services.archive import ArchiveService
from services.processing.types import UploadArguments
from services.test_results import generate_flags_hash, generate_test_id
from services.yaml import read_yaml_field
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


@dataclass
class ReadableFile:
    path: str
    contents: bytes


class ParserFailureError(Exception):
    def __init__(self, err_msg, file_content, parser="", parser_err_msg=""):
        self.err_msg = err_msg
        self.file_content = file_content
        self.parser = parser
        self.parser_err_msg = parser_err_msg


class ParserNotSupportedError(Exception): ...


def get_existing_flag_bridges(
    db_session: Session, repoid: int, flags: list[str]
) -> dict[str, TestFlagBridge]:
    existing_flag_bridges = (
        db_session.query(TestFlagBridge)
        .join(RepositoryFlag, TestFlagBridge.flag_id == RepositoryFlag.id_)
        .filter(RepositoryFlag.repository_id == repoid)
        .all()
    )
    return {flag_bridge.test_id: flag_bridge for flag_bridge in existing_flag_bridges}


def get_repo_flags(
    db_session: Session, repoid: int, flags: list[str]
) -> dict[str, int]:
    repo_flags: list[RepositoryFlag] = (
        db_session.query(RepositoryFlag)
        .filter(
            RepositoryFlag.repository_id == repoid,
            RepositoryFlag.flag_name.in_(flags),
        )
        .all()
    )

    # flag name => flag id
    repo_flag_mapping: dict[str, int] = {
        repo_flag.flag_name: repo_flag.id_ for repo_flag in repo_flags
    }

    return repo_flag_mapping


@dataclass
class PytestName:
    actual_class_name: str
    test_file_path: str


@dataclass
class TestResultsProcessingResult:
    network_files: list[str] | None
    parsing_results: list[ParsingInfo]


class TestResultsProcessorTask(BaseCodecovTask, name=test_results_processor_task_name):
    __test__ = False

    def run_impl(
        self,
        db_session,
        *args,
        repoid: int,
        commitid: str,
        commit_yaml,
        arguments_list: list[UploadArguments],
        **kwargs,
    ):
        log.info("Received upload test result processing task")

        commit_yaml = UserYaml(commit_yaml)
        repoid = int(repoid)

        results = []
        upload_list = []

        repo_flakes = (
            db_session.query(Flake.testid)
            .filter(Flake.repoid == repoid, Flake.end_date.is_(None))
            .all()
        )
        flaky_test_set = {flake.testid for flake in repo_flakes}

        # process each report session's test information
        for arguments in arguments_list:
            upload = (
                db_session.query(Upload).filter_by(id_=arguments["upload_id"]).first()
            )
            result = self.process_individual_upload(
                db_session, repoid, commitid, upload, flaky_test_set
            )

            results.append(result)
            upload_list.append(upload)

        if self.should_delete_archive(commit_yaml):
            repository = (
                db_session.query(Repository)
                .filter(Repository.repoid == int(repoid))
                .first()
            )
            self.delete_archive(
                commitid, repository, commit_yaml, uploads_to_delete=upload_list
            )

        return results

    def _bulk_write_tests_to_db(
        self,
        db_session: Session,
        repoid: int,
        commitid: str,
        upload_id: int,
        branch: str,
        parsing_results: List[ParsingInfo],
        network: list[str] | None,
        flaky_test_set: set[str],
        flags: list[str],
    ):
        test_data = {}
        test_instance_data = []
        test_flag_bridge_data = []
        daily_totals: dict[str, dict[str, str | int | list[str]]] = dict()
        flags_hash = generate_flags_hash(flags)

        repo_flags: dict[str, int] = get_repo_flags(db_session, repoid, flags)

        existing_flag_bridges: dict[str, TestFlagBridge] = get_existing_flag_bridges(
            db_session, repoid, flags
        )

        for p in parsing_results:
            framework = str(p.framework) if p.framework else None

            for testrun in p.testruns:
                # Build up the data for bulk insert
                name: str = f"{testrun.classname}\x1f{testrun.name}"
                testsuite: str = testrun.testsuite
                outcome: str = str(testrun.outcome)
                duration_seconds: float = testrun.duration
                failure_message: str | None = testrun.failure_message
                test_id: str = generate_test_id(repoid, testsuite, name, flags_hash)

                filename: str | None = testrun.filename

                test_data[(repoid, name, testsuite, flags_hash)] = dict(
                    id=test_id,
                    repoid=repoid,
                    name=name,
                    testsuite=testsuite,
                    flags_hash=flags_hash,
                    framework=framework,
                    filename=filename,
                    computed_name=testrun.computed_name,
                )

                if test_id not in existing_flag_bridges and flags:
                    test_flag_bridge_data += [
                        {"test_id": test_id, "flag_id": repo_flags[flag]}
                        for flag in flags
                    ]

                test_instance_data.append(
                    dict(
                        test_id=test_id,
                        upload_id=upload_id,
                        duration_seconds=duration_seconds,
                        outcome=outcome,
                        failure_message=failure_message,
                        commitid=commitid,
                        branch=branch,
                        reduced_error_id=None,
                        repoid=repoid,
                    )
                )

                def update_daily_total():
                    daily_totals[test_id]["last_duration_seconds"] = duration_seconds

                    # logic below is a little complicated but we're basically doing:

                    # (old_avg * num of values used to compute old avg) + new value
                    # -------------------------------------------------------------
                    #          num of values used to compute old avg + 1
                    daily_totals[test_id]["avg_duration_seconds"] = (
                        daily_totals[test_id]["avg_duration_seconds"]
                        * (
                            daily_totals[test_id]["pass_count"]
                            + daily_totals[test_id]["fail_count"]
                        )
                        + duration_seconds
                    ) / (
                        daily_totals[test_id]["pass_count"]
                        + daily_totals[test_id]["fail_count"]
                        + 1
                    )

                    if outcome == str(Outcome.Pass):
                        daily_totals[test_id]["pass_count"] += 1
                    elif outcome == str(Outcome.Failure) or outcome == str(
                        Outcome.Error
                    ):
                        daily_totals[test_id]["fail_count"] += 1
                    elif outcome == str(Outcome.Skip):
                        daily_totals[test_id]["skip_count"] += 1

                def create_daily_total():
                    daily_totals[test_id] = {
                        "test_id": test_id,
                        "repoid": repoid,
                        "last_duration_seconds": duration_seconds,
                        "avg_duration_seconds": duration_seconds,
                        "pass_count": 1 if outcome == str(Outcome.Pass) else 0,
                        "fail_count": 1
                        if outcome == str(Outcome.Failure)
                        or outcome == str(Outcome.Error)
                        else 0,
                        "skip_count": 1 if outcome == str(Outcome.Skip) else 0,
                        "flaky_fail_count": 1
                        if test_id in flaky_test_set
                        and (
                            outcome == str(Outcome.Failure)
                            or outcome == str(Outcome.Error)
                        )
                        else 0,
                        "branch": branch,
                        "date": date.today(),
                        "latest_run": datetime.now(),
                        "commits_where_fail": [commitid]
                        if (
                            outcome == str(Outcome.Failure)
                            or outcome == str(Outcome.Error)
                        )
                        else [],
                    }

                if outcome != str(Outcome.Skip):
                    if test_id in daily_totals:
                        update_daily_total()
                    else:
                        create_daily_total()

        # Upsert Tests
        if len(test_data) > 0:
            test_insert = insert(Test.__table__).values(
                sorted(test_data.values(), key=lambda x: str(x["flags_hash"]))
            )
            insert_on_conflict_do_update = test_insert.on_conflict_do_update(
                index_elements=["repoid", "name", "testsuite", "flags_hash"],
                set_={
                    "framework": test_insert.excluded.framework,
                    "computed_name": test_insert.excluded.computed_name,
                    "filename": test_insert.excluded.filename,
                },
            )
            db_session.execute(insert_on_conflict_do_update)
            db_session.flush()

        if len(test_flag_bridge_data):
            insert_on_conflict_do_nothing_flags = (
                insert(TestFlagBridge.__table__)
                .values(test_flag_bridge_data)
                .on_conflict_do_nothing(index_elements=["test_id", "flag_id"])
            )
            db_session.execute(insert_on_conflict_do_nothing_flags)
            db_session.flush()

        # Upsert Daily Test Totals
        if len(daily_totals) > 0:
            rollup_table = DailyTestRollup.__table__
            stmt = insert(rollup_table).values(
                sorted(daily_totals.values(), key=lambda x: str(x["test_id"]))
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "repoid",
                    "branch",
                    "test_id",
                    "date",
                ],
                set_={
                    "last_duration_seconds": stmt.excluded.last_duration_seconds,
                    "avg_duration_seconds": (
                        rollup_table.c.avg_duration_seconds
                        * (rollup_table.c.pass_count + rollup_table.c.fail_count)
                        + stmt.excluded.avg_duration_seconds
                    )
                    / (rollup_table.c.pass_count + rollup_table.c.fail_count + 1),
                    "latest_run": stmt.excluded.latest_run,
                    "pass_count": rollup_table.c.pass_count + stmt.excluded.pass_count,
                    "skip_count": rollup_table.c.skip_count + stmt.excluded.skip_count,
                    "fail_count": rollup_table.c.fail_count + stmt.excluded.fail_count,
                    "flaky_fail_count": rollup_table.c.flaky_fail_count
                    + stmt.excluded.flaky_fail_count,
                    "commits_where_fail": rollup_table.c.commits_where_fail
                    + stmt.excluded.commits_where_fail,
                },
            )

            db_session.execute(stmt)
            db_session.flush()

        # Save TestInstances
        if len(test_instance_data) > 0:
            insert_test_instances = insert(TestInstance.__table__).values(
                test_instance_data
            )
            db_session.execute(insert_test_instances)
            db_session.flush()

    def process_individual_upload(
        self, db_session, repoid, commitid, upload_obj: Upload, flaky_test_set: set[str]
    ):
        upload_id = upload_obj.id
        with metrics.timer("test_results.processor.process_individual_arg"):
            arg_processing_result: TestResultsProcessingResult = (
                self.process_individual_arg(
                    upload_obj, upload_obj.report.commit.repository
                )
            )
        if all(
            [
                len(result.testruns) == 0
                for result in arg_processing_result.parsing_results
            ]
        ):
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
        upload_id = upload_obj.id
        branch = upload_obj.report.commit.branch
        self._bulk_write_tests_to_db(
            db_session,
            repoid,
            commitid,
            upload_id,
            branch,
            arg_processing_result.parsing_results,
            arg_processing_result.network_files,
            flaky_test_set,
            upload_obj.flag_names,
        )

        return {
            "successful": True,
        }

    def rewrite_readable(
        self, network: list[str] | None, report_contents: list[ReadableFile]
    ):
        buffer = BytesIO()
        if network is not None:
            for path in network:
                buffer.write(f"# path={path}\n".encode("utf-8"))
            buffer.write(b"<<<<<< network\n\n")
        for report_content in report_contents:
            buffer.write(f"# path={report_content.path}\n".encode("utf-8"))
            buffer.write(report_content.contents)
            buffer.write(b"\n<<<<<< EOF\n\n")
        buffer.seek(0)
        return buffer

    def process_individual_arg(
        self, upload: Upload, repository
    ) -> TestResultsProcessingResult:
        archive_service = ArchiveService(repository)

        payload_bytes = archive_service.read_file(upload.storage_path)
        data = json.loads(payload_bytes)

        parsing_results: list[ParsingInfo] = []

        network: list[str] | None = data.get("network_files")

        report_contents = []

        for file_dict in data["test_results_files"]:
            file = file_dict["data"]
            file_bytes = BytesIO(zlib.decompress(base64.b64decode(file)))
            report_contents.append(
                ReadableFile(path=file_dict["filename"], contents=file_bytes.getvalue())
            )
            try:
                parsing_results.append(self.parse_single_file(file_bytes))
            except ParserFailureError as exc:
                log.error(
                    exc.err_msg,
                    extra=dict(
                        repoid=upload.report.commit.repoid,
                        commitid=upload.report.commit_id,
                        uploadid=upload.id,
                        file_content=exc.file_content,
                        parser_err_msg=exc.parser_err_msg,
                    ),
                )

        readable_report = self.rewrite_readable(network, report_contents)
        archive_service.write_file(upload.storage_path, readable_report.getvalue())

        return TestResultsProcessingResult(
            network_files=network, parsing_results=parsing_results
        )

    def parse_single_file(
        self,
        file_bytes: BytesIO,
    ):
        try:
            file_content = file_bytes.read()
            with metrics.timer("test_results.processor.file_parsing"):
                res = parse_junit_xml(file_content)
        except ParserError as e:
            metrics.incr(
                "test_results.processor.parsing.failure.failed_to_parse",
            )
            raise ParserFailureError(
                err_msg="Error parsing file",
                file_content=file_content.decode()[:300],
                parser_err_msg=str(e),
            ) from e
        metrics.incr(
            "test_results.processor.parsing.success",
        )

        return res

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
