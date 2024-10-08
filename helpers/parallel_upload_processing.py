import sentry_sdk


@sentry_sdk.trace
def save_incremental_report_results(
    report_service, commit, report, upload_id, report_code
):
    commitid = commit.commitid
    archive_service = report_service.get_archive_service(commit.repository)

    # Save incremental results to archive storage,
    # upload_finisher will combine
    chunks = report.to_archive().encode()
    _, files_and_sessions = report.to_database()

    chunks_url = archive_service.write_parallel_experiment_file(
        commitid, chunks, report_code, f"incremental/chunk{upload_id}"
    )
    files_and_sessions_url = archive_service.write_parallel_experiment_file(
        commitid,
        files_and_sessions,
        report_code,
        f"incremental/files_and_sessions{upload_id}",
    )

    parallel_incremental_result = {
        "upload_pk": upload_id,
        "chunks_path": chunks_url,
        "files_and_sessions_path": files_and_sessions_url,
    }
    return parallel_incremental_result


# Saves the result of the an entire serial processing flow to archive storage
# so that it can be compared for parallel experiment. Not necessarily the final report
# for the commit, if more uploads are still made.
@sentry_sdk.trace
def save_final_serial_report_results(
    report_service, commit, report, report_code, arguments_list
):
    commitid = commit.commitid
    archive_service = report_service.get_archive_service(commit.repository)

    # We identify the final result of an entire serial processing pipeline
    # by the upload_pk of the very last upload received (ie the last element
    # in arguments_list), and this is how each parallel verification task
    # knows where to find the corresponding report to compare with for a given flow
    latest_upload_pk = arguments_list[-1].get("upload_pk")

    chunks = report.to_archive().encode()
    _, files_and_sessions = report.to_database()

    archive_service.write_parallel_experiment_file(
        commitid,
        chunks,
        report_code,
        f"serial/chunks<latest_upload_pk:{latest_upload_pk}>",
    )
    report_url = archive_service.write_parallel_experiment_file(
        commitid,
        files_and_sessions,
        report_code,
        f"serial/files_and_sessions<latest_upload_pk:{latest_upload_pk}>",
    )
    return report_url
