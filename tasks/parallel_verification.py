import copy
import json
import logging

from shared.celery_config import parallel_verification_task_name

from app import celery_app
from database.models import Commit
from services.report import ReportService
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ParallelVerificationTask(BaseCodecovTask, name=parallel_verification_task_name):
    def run_impl(
        self,
        db_session,
        *,
        repoid,
        commitid,
        commit_yaml,
        report_code,
        parallel_paths,
        **kwargs,
    ):
        commits = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits.first()
        assert commit, "Commit not found in database."

        repository = commit.repository

        report_service = ReportService(commit_yaml)
        archive_service = report_service.get_archive_service(repository)

        log.info(
            "Starting parallel upload processsing verification task",
            extra=dict(
                repoid=repoid,
                commitid=commitid,
                commit_yaml=commit_yaml,
                report_code=report_code,
                parallel_paths=parallel_paths,
            ),
        )

        # Retrieve parallel results
        parallel_files_and_sessions = sort_and_stringify_report_json(
            json.loads(
                archive_service.read_file(parallel_paths["files_and_sessions_path"])
            )
        )
        parallel_chunks = archive_service.read_file(
            parallel_paths["chunks_path"]
        ).decode(errors="replace")

        # Retrieve serial results using legacy method
        l_files = commit.report_json["files"]
        l_sessions = commit.report_json["sessions"]
        l_files_and_sessions = sort_and_stringify_report_json(
            {"files": l_files, "sessions": l_sessions}
        )

        # Retrieve serial results
        report = report_service.get_existing_report_for_commit(commit)
        _, files_and_sessions = report.to_database()
        files_and_sessions = sort_and_stringify_report_json(
            json.loads(files_and_sessions)
        )
        chunks = archive_service.read_chunks(commitid, report_code)

        fas_legacy = parallel_files_and_sessions == l_files_and_sessions
        fas_regular = parallel_files_and_sessions == files_and_sessions
        chunks_regular = parallel_chunks == chunks

        if not fas_legacy:
            log.info(
                "Legacy files and sessions did not match parallel results",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    report_code=report_code,
                    parallel_paths=parallel_paths,
                ),
            )
        if not fas_regular:
            log.info(
                "Files and sessions did not match parallel results",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    report_code=report_code,
                    parallel_paths=parallel_paths,
                ),
            )
        if not chunks_regular:
            log.info(
                "chunks did not match parallel results",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    report_code=report_code,
                    parallel_paths=parallel_paths,
                ),
            )

        verification_result = (
            (1 if fas_legacy else 0)
            + (1 if fas_regular else 0)
            + (1 if chunks_regular else 0)
        ) / 3

        if verification_result == 1:
            log.info(
                "Parallel upload processsing verification succeeded",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    report_code=report_code,
                    parallel_paths=parallel_paths,
                ),
            )
        else:
            log.info(
                f"Parallel upload processsing verification failed with {verification_result}",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    report_code=report_code,
                    parallel_paths=parallel_paths,
                ),
            )

        return


# To filter out values not relevant for verifying report content correctness. We
# don't want these values to be the reason why there exists a diff, since it's
# not actually related to coverage report contents
def sort_and_stringify_report_json(data):
    data = copy.deepcopy(data)
    for session_id in data["sessions"].keys():
        data["sessions"][session_id].pop("d", None)  # remove timestamp
        data["sessions"][session_id].pop("e", None)  # remove env
        data["sessions"][session_id].pop("p", None)  # remove state
        data["sessions"][session_id].pop("se", None)  # remove session extras
        if data["sessions"][session_id]["f"] is None:  # flags formatting
            data["sessions"][session_id]["f"] = []

        # round the coverage precentage to 2 decimals (because we're inconsistent somewhere)
        if "t" in data["sessions"][session_id]:
            data["sessions"][session_id]["t"][5] = str(
                round(float(data["sessions"][session_id]["t"][5]), 2)
            )

    return json.dumps(data, sort_keys=True)


RegisteredParallelVerificationTask = celery_app.register_task(
    ParallelVerificationTask()
)
parallel_verification_task = celery_app.tasks[RegisteredParallelVerificationTask.name]
