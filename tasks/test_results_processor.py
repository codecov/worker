import base64
import json
import logging
import zlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import TypedDict

import sentry_sdk
from shared.celery_config import test_results_processor_task_name
from shared.config import get_config
from shared.yaml import UserYaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from test_results_parser import Outcome, ParserError, ParsingInfo, parse_junit_xml

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


def get_repo_flag_ids(db_session: Session, repoid: int, flags: list[str]) -> set[int]:
    if not flags:
        return set()

    return set(
        db_session.query(RepositoryFlag.id_)
        .filter(
            RepositoryFlag.repository_id == repoid,
            RepositoryFlag.flag_name.in_(flags),
        )
        .all()
    )


def create_daily_totals(
    daily_totals: dict,
    test_id: str,
    repoid: int,
    duration_seconds: float,
    outcome: Outcome,
    branch: str,
    commitid: str,
    flaky_test_set: set[str],
):
    daily_totals[test_id] = {
        "test_id": test_id,
        "repoid": repoid,
        "last_duration_seconds": duration_seconds,
        "avg_duration_seconds": duration_seconds,
        "pass_count": 1 if outcome == str(Outcome.Pass) else 0,
        "fail_count": 1
        if outcome == str(Outcome.Failure) or outcome == str(Outcome.Error)
        else 0,
        "skip_count": 1 if outcome == str(Outcome.Skip) else 0,
        "flaky_fail_count": 1
        if test_id in flaky_test_set
        and (outcome == str(Outcome.Failure) or outcome == str(Outcome.Error))
        else 0,
        "branch": branch,
        "date": date.today(),
        "latest_run": datetime.now(),
        "commits_where_fail": [commitid]
        if (outcome == str(Outcome.Failure) or outcome == str(Outcome.Error))
        else [],
    }


def update_daily_totals(
    daily_totals: dict,
    test_id: str,
    duration_seconds: float,
    outcome: Outcome,
):
    daily_totals[test_id]["last_duration_seconds"] = duration_seconds

    # logic below is a little complicated but we're basically doing:

    # (old_avg * num of values used to compute old avg) + new value
    # -------------------------------------------------------------
    #          num of values used to compute old avg + 1
    daily_totals[test_id]["avg_duration_seconds"] = (
        daily_totals[test_id]["avg_duration_seconds"]
        * (daily_totals[test_id]["pass_count"] + daily_totals[test_id]["fail_count"])
        + duration_seconds
    ) / (daily_totals[test_id]["pass_count"] + daily_totals[test_id]["fail_count"] + 1)

    if outcome == str(Outcome.Pass):
        daily_totals[test_id]["pass_count"] += 1
    elif outcome == str(Outcome.Failure) or outcome == str(Outcome.Error):
        daily_totals[test_id]["fail_count"] += 1
    elif outcome == str(Outcome.Skip):
        daily_totals[test_id]["skip_count"] += 1


@dataclass
class PytestName:
    actual_class_name: str
    test_file_path: str


class DailyTotals(TypedDict):
    test_id: str
    repoid: int
    pass_count: int
    fail_count: int
    skip_count: int
    flaky_fail_count: int
    branch: str
    date: date
    latest_run: datetime
    commits_where_fail: list[str]
    last_duration_seconds: float
    avg_duration_seconds: float


class TestResultsProcessorTask(BaseCodecovTask, name=test_results_processor_task_name):
    __test__ = False

    def run_impl(
        self,
        db_session,
        previous_result: bool,
        *args,
        repoid: int,
        commitid: str,
        commit_yaml,
        arguments_list: list[UploadArguments],
        **kwargs,
    ) -> bool:
        log.info("Received upload test result processing task")

        commit_yaml = UserYaml(commit_yaml)
        repoid = int(repoid)

        results = []

        repo_flakes = (
            db_session.query(Flake.testid)
            .filter(Flake.repoid == repoid, Flake.end_date.is_(None))
            .all()
        )
        flaky_test_set = {flake.testid for flake in repo_flakes}
        repository = (
            db_session.query(Repository)
            .filter(Repository.repoid == int(repoid))
            .first()
        )

        should_delete_archive = self.should_delete_archive(commit_yaml)
        archive_service = ArchiveService(repository)

        # process each report session's test information
        for arguments in arguments_list:
            upload = (
                db_session.query(Upload).filter_by(id_=arguments["upload_id"]).first()
            )
            result = self.process_individual_upload(
                db_session,
                archive_service,
                repository,
                commitid,
                upload,
                flaky_test_set,
                should_delete_archive,
            )

            results.append(result)

        return previous_result or any(result.get("successful") for result in results)

    @sentry_sdk.trace
    def _bulk_write_tests_to_db(
        self,
        db_session: Session,
        repoid: int,
        commitid: str,
        upload_id: int,
        branch: str,
        parsing_results: list[ParsingInfo],
        flaky_test_set: set[str],
        flags: list[str],
    ):
        log.info("Writing tests to database", extra=dict(upload_id=upload_id))
        test_data = {}
        test_instance_data = []
        test_flag_bridge_data: list[dict] = []
        daily_totals: dict[str, DailyTotals] = dict()

        flags_hash = generate_flags_hash(flags)
        repo_flag_ids = get_repo_flag_ids(db_session, repoid, flags)

        for p in parsing_results:
            framework = str(p.framework) if p.framework else None

            for testrun in p.testruns:
                # Build up the data for bulk insert
                name: str = f"{testrun.classname}\x1f{testrun.name}"
                testsuite: str = testrun.testsuite
                outcome: str = str(testrun.outcome)
                duration_seconds: float = (
                    testrun.duration if testrun.duration is not None else 0.0
                )
                failure_message: str | None = testrun.failure_message
                test_id: str = generate_test_id(repoid, testsuite, name, flags_hash)
                computed_name = testrun.computed_name

                filename: str | None = testrun.filename

                test_data[(repoid, name, testsuite, flags_hash)] = dict(
                    id=test_id,
                    repoid=repoid,
                    name=name,
                    testsuite=testsuite,
                    flags_hash=flags_hash,
                    framework=framework,
                    filename=filename,
                    computed_name=computed_name,
                )

                if repo_flag_ids:
                    test_flag_bridge_data.extend(
                        {"test_id": test_id, "flag_id": flag_id}
                        for flag_id in repo_flag_ids
                    )

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

                if outcome != str(Outcome.Skip):
                    if test_id in daily_totals:
                        update_daily_totals(
                            daily_totals, test_id, duration_seconds, outcome
                        )
                    else:
                        create_daily_totals(
                            daily_totals,
                            test_id,
                            repoid,
                            duration_seconds,
                            outcome,
                            branch,
                            commitid,
                            flaky_test_set,
                        )

        # Upsert Tests
        if len(test_data) > 0:
            metrics.gauge("test_results_processor.test_count", len(test_data))
            sorted_tests = sorted(
                test_data.values(),
                key=lambda x: str(x["id"]),
            )
            self.save_tests(db_session, sorted_tests)

            log.info("Upserted tests to database", extra=dict(upload_id=upload_id))

        if len(test_flag_bridge_data) > 0:
            self.save_test_flag_bridges(db_session, test_flag_bridge_data)

            log.info(
                "Inserted new test flag bridges to database",
                extra=dict(upload_id=upload_id),
            )

        if len(daily_totals) > 0:
            sorted_rollups = sorted(
                daily_totals.values(), key=lambda x: str(x["test_id"])
            )
            self.save_daily_test_rollups(db_session, sorted_rollups)

            log.info(
                "Upserted daily test rollups to database",
                extra=dict(upload_id=upload_id),
            )

        # Save TestInstances
        if len(test_instance_data) > 0:
            metrics.gauge(
                "test_results_processor.test_instance_count", len(test_instance_data)
            )
            self.save_test_instances(db_session, test_instance_data)

            log.info(
                "Inserted test instances to database", extra=dict(upload_id=upload_id)
            )

    def save_tests(self, db_session: Session, test_data: list[dict]):
        test_insert = insert(Test.__table__).values(test_data)
        insert_on_conflict_do_update = test_insert.on_conflict_do_update(
            index_elements=["repoid", "name", "testsuite", "flags_hash"],
            set_={
                "framework": test_insert.excluded.framework,
                "computed_name": test_insert.excluded.computed_name,
                "filename": test_insert.excluded.filename,
            },
        )
        db_session.execute(insert_on_conflict_do_update)
        db_session.commit()

    def save_daily_test_rollups(self, db_session: Session, daily_rollups: list[dict]):
        rollup_table = DailyTestRollup.__table__
        stmt = insert(rollup_table).values(daily_rollups)
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
        db_session.commit()

    def save_test_instances(self, db_session: Session, test_instance_data: list[dict]):
        insert_test_instances = insert(TestInstance.__table__).values(
            test_instance_data
        )
        db_session.execute(insert_test_instances)
        db_session.commit()

    def save_test_flag_bridges(
        self, db_session: Session, test_flag_bridge_data: list[dict]
    ):
        insert_on_conflict_do_nothing_flags = (
            insert(TestFlagBridge.__table__)
            .values(test_flag_bridge_data)
            .on_conflict_do_nothing(index_elements=["test_id", "flag_id"])
        )
        db_session.execute(insert_on_conflict_do_nothing_flags)
        db_session.commit()

    def decode_raw_file(self, file: bytes) -> bytes:
        file_bytes = zlib.decompress(base64.b64decode(file))
        return file_bytes

    def parse_file(
        self, file_bytes: bytes, upload: Upload, parsing_results: list[ParsingInfo]
    ) -> bool:
        try:
            parsing_results.append(parse_junit_xml(file_bytes))
            return True
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
            return False

    def process_individual_upload(
        self,
        db_session,
        archive_service: ArchiveService,
        repository: Repository,
        commitid,
        upload: Upload,
        flaky_test_set: set[str],
        should_delete_archive: bool,
    ):
        upload_id = upload.id

        log.info("Processing individual upload", extra=dict(upload_id=upload_id))
        if upload.state == "processed":
            return {"successful": True}
        elif upload.state == "has_failed":
            return {"successful": False}

        payload_bytes = archive_service.read_file(upload.storage_path)
        try:
            data = json.loads(payload_bytes)
        except json.JSONDecodeError as e:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("upload_state", upload.state)
                sentry_sdk.capture_exception(e, scope)

                upload.state = "not parsed"
                db_session.flush()
                return {"successful": False}

        parsing_results: list[ParsingInfo] = []
        network: list[str] | None = data.get("network_files")
        report_contents: list[ReadableFile] = []

        all_succesful = True
        for file_dict in data["test_results_files"]:
            file = file_dict["data"]
            file_bytes = self.decode_raw_file(file)
            report_contents.append(
                ReadableFile(path=file_dict["filename"], contents=file_bytes)
            )
            success = self.parse_file(file_bytes, upload, parsing_results)
            if not success:
                all_succesful = False

        if all_succesful:
            upload.state = "processed"
        else:
            upload.state = "has_failed"

        if all(len(result.testruns) == 0 for result in parsing_results):
            successful = False
            log.error(
                "No test result files were successfully parsed for this upload",
                extra=dict(upload_id=upload_id),
            )
        else:
            successful = True

            self._bulk_write_tests_to_db(
                db_session,
                repository.repoid,
                commitid,
                upload_id,
                upload.report.commit.branch,
                parsing_results,
                flaky_test_set,
                upload.flag_names,
            )

        db_session.commit()

        log.info(
            "Finished processing individual upload", extra=dict(upload_id=upload_id)
        )

        if should_delete_archive:
            self.delete_archive(archive_service, upload)
        else:
            readable_report = self.rewrite_readable(network, report_contents)
            archive_service.write_file(upload.storage_path, readable_report)

        return {"successful": successful}

    def rewrite_readable(
        self, network: list[str] | None, report_contents: list[ReadableFile]
    ) -> bytes:
        buffer = b""
        if network is not None:
            for file in network:
                buffer += f"{file}\n".encode("utf-8")
            buffer += b"<<<<<< network\n\n"
        for report_content in report_contents:
            buffer += f"# path={report_content.path}\n".encode("utf-8")
            buffer += report_content.contents
            buffer += b"\n<<<<<< EOF\n\n"
        return buffer

    def should_delete_archive(self, commit_yaml):
        if get_config("services", "minio", "expire_raw_after_n_days"):
            return True
        return not read_yaml_field(
            commit_yaml, ("codecov", "archive", "uploads"), _else=True
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


RegisteredTestResultsProcessorTask = celery_app.register_task(
    TestResultsProcessorTask()
)
test_results_processor_task = celery_app.tasks[RegisteredTestResultsProcessorTask.name]
