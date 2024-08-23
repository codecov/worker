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
        logging_context = dict(
            repoid=repoid,
            commitid=commitid,
            commit_yaml=commit_yaml,
            report_code=report_code,
            parallel_paths=parallel_paths,
        )
        commit = (
            db_session.query(Commit)
            .filter(Commit.repoid == repoid, Commit.commitid == commitid)
            .first()
        )
        assert commit, "Commit not found in database."

        report_service = ReportService(commit_yaml)
        archive_service = report_service.get_archive_service(commit.repository)

        log.info(
            "Starting parallel upload processing verification task",
            extra=logging_context,
        )

        # Retrieve parallel results
        parallel_files_and_sessions = json.loads(
            archive_service.read_file(parallel_paths["files_and_sessions_path"])
        )
        parallel_chunks = archive_service.read_file(
            parallel_paths["chunks_path"]
        ).decode(errors="replace")
        parallel_report = report_service.build_report(
            parallel_chunks,
            parallel_files_and_sessions["files"],
            parallel_files_and_sessions["sessions"],
            None,
        )

        # TODO: ensure the legacy report building method (`commit.report_json["files"]`) is accurate aswell. There's
        # no easy way to do this right now because the legacy method assumes the
        # report to build lives in the database, but the report we want to compare
        # for the verification experiment lives in archive storage.

        # the pk of the last upload for the processing pipeline
        last_upload_pk = processing_results["processings_so_far"][-1]["arguments"].get(
            "upload_pk"
        )

        # Retrieve serial results
        serial_files_and_sessions = json.loads(
            archive_service.read_file(
                parallel_path_to_serial_path(
                    parallel_paths["files_and_sessions_path"], last_upload_pk
                )
            )
        )
        serial_chunks = archive_service.read_file(
            parallel_path_to_serial_path(parallel_paths["chunks_path"], last_upload_pk)
        ).decode(errors="replace")
        serial_report = report_service.build_report(
            serial_chunks,
            serial_files_and_sessions["files"],
            serial_files_and_sessions["sessions"],
            None,
        )

        top_level_totals_match = True
        file_level_totals_match = True
        file_level_mismatched_files = []

        # top level totals comparison (ignoring session total, index 9)
        parallel_tlt = list(parallel_report.totals.astuple())
        serial_tlt = list(serial_report.totals.astuple())
        parallel_tlt[9] = (
            0  # 9th index is session total for shared.reports.types.ReportTotals
        )
        serial_tlt[9] = 0
        if parallel_tlt != serial_tlt:
            top_level_totals_match = False

        # file level totals comparison
        for filename, file_summary in parallel_report._files.items():
            parallel_file_level_totals = file_summary.file_totals

            if filename in serial_report._files:
                serial_file_level_totals = serial_report._files[filename].file_totals

                if serial_file_level_totals != parallel_file_level_totals:
                    file_level_mismatched_files.append(filename)
                    file_level_totals_match = False
            else:
                file_level_totals_match = False

        if len(parallel_report._files) != len(serial_report._files):
            log.info("Number of files did not match", extra=logging_context)

        verification_result = (
            (1 if top_level_totals_match else 0) + (1 if file_level_totals_match else 0)
        ) / 2

        if not top_level_totals_match:
            log.info(
                "Top level totals did not match",
                extra=dict(
                    logging_context,
                    parallel_totals=parallel_report.totals.astuple(),
                    serial_totals=serial_report.totals.astuple(),
                ),
            )

        if not file_level_totals_match:
            log.info(
                "File level totals did not match",
                extra=dict(
                    logging_context,
                    mismatched_files=file_level_mismatched_files,
                ),
            )

        log.info(
            f"Parallel upload processing verification {'succeeded' if verification_result == 1 else 'failed with ' + str(verification_result)}",
            extra=logging_context,
        )


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
