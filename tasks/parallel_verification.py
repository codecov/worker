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
        processing_results,
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
            "Starting parallel upload processing verification task",
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

        # TODO: ensure the legacy report building method (`commit.report_json["files"]`) is accurate aswell. There's
        # no easy way to do this right now because the legacy method assumes the
        # report to build lives in the database, but the report we want to compare
        # for the verification experiment lives in archive storage.

        # the pk of the last upload for the processing pipeline
        last_upload_pk = processing_results["processings_so_far"][-1]["arguments"].get(
            "upload_pk"
        )

        # Retrieve serial results
        files_and_sessions = sort_and_stringify_report_json(
            json.loads(
                archive_service.read_file(
                    parallel_path_to_serial_path(
                        parallel_paths["files_and_sessions_path"], last_upload_pk
                    )
                )
            )
        )
        chunks = archive_service.read_file(
            parallel_path_to_serial_path(parallel_paths["chunks_path"], last_upload_pk)
        ).decode(errors="replace")

        fas_comparison_result = parallel_files_and_sessions == files_and_sessions
        chunks_comparison_result = parallel_chunks == chunks

        if not fas_comparison_result:
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
        if not chunks_comparison_result:
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
            (1 if fas_comparison_result else 0) + (1 if chunks_comparison_result else 0)
        ) / 2

        if verification_result == 1:
            log.info(
                "Parallel upload processing verification succeeded",
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
                f"Parallel upload processing verification failed with {verification_result}",
                extra=dict(
                    repoid=repoid,
                    commitid=commitid,
                    commit_yaml=commit_yaml,
                    report_code=report_code,
                    parallel_paths=parallel_paths,
                ),
            )

        return


def parallel_path_to_serial_path(parallel_path, last_upload_pk):
    parallel_paths = parallel_path.split("/")
    cur_file = parallel_paths.pop().removesuffix(
        ".txt"
    )  # either chunks.txt, <report_code>.txt, or files_and_sessions.txt
    serial_path = (
        "/".join(parallel_paths)
        + f"/serial/{cur_file}<latest_upload_pk:{str(last_upload_pk)}>.txt"
    )
    return serial_path


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
