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
