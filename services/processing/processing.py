import logging
from collections.abc import Callable

import sentry_sdk
from celery.exceptions import CeleryError
from shared.yaml import UserYaml
from sqlalchemy.orm import Session as DbSession

from database.models.core import Commit
from database.models.reports import Upload
from helpers.reports import delete_archive_setting
from services.archive import ArchiveService
from services.report import ProcessingError, RawReportInfo, Report, ReportService
from services.report.parser.types import VersionOneParsedRawReport

from .intermediate import save_intermediate_report
from .state import ProcessingState
from .types import ProcessingResult, UploadArguments

log = logging.getLogger(__name__)


@sentry_sdk.trace
def process_upload(
    on_processing_error: Callable[[ProcessingError], None],
    db_session: DbSession,
    repo_id: int,
    commit_sha: str,
    commit_yaml: UserYaml,
    arguments: UploadArguments,
    intermediate_reports_in_redis=False,
) -> ProcessingResult:
    upload_id = arguments["upload_id"]

    commit = (
        db_session.query(Commit)
        .filter(Commit.repoid == repo_id, Commit.commitid == commit_sha)
        .first()
    )
    assert commit

    upload = db_session.query(Upload).filter_by(id_=upload_id).first()
    assert upload

    state = ProcessingState(repo_id, commit_sha)
    # this in a noop in normal cases, but relevant for task retries:
    state.mark_uploads_as_processing([upload_id])

    report_service = ReportService(commit_yaml)
    archive_service = report_service.get_archive_service(commit.repository)

    result = ProcessingResult(
        upload_id=upload_id, arguments=arguments, successful=False
    )

    try:
        report_info = RawReportInfo()
        processing_result = report_service.build_report_from_raw_content(
            report_info, upload
        )

        if error := processing_result.error:
            on_processing_error(error)  # NOTE: this might throw a `Retry`
            result["error"] = error.as_dict()
        else:
            result["successful"] = True
        log.info("Finished processing upload", extra={"result": result})

        # TODO(swatinem): only save the intermediate report on success
        save_intermediate_report(
            archive_service,
            commit_sha,
            upload_id,
            processing_result.report or Report(),
            intermediate_reports_in_redis,
        )
        state.mark_upload_as_processed(upload_id)

        rewrite_or_delete_upload(archive_service, commit_yaml, report_info)

    except CeleryError:
        raise
    except Exception:
        commit.state = "error"
        db_session.commit()
        log.exception("Could not properly process commit")
        raise

    finally:
        # this is a noop in the success case, but makes sure unrecoverable errors
        # or retries are not blocking later merge/notify stages
        state.clear_in_progress_uploads([upload_id])

    return result


def rewrite_or_delete_upload(
    archive_service: ArchiveService, commit_yaml: UserYaml, report_info: RawReportInfo
):
    should_delete_archive_setting = delete_archive_setting(commit_yaml)
    archive_url = report_info.archive_url

    if should_delete_archive_setting and not report_info.error:
        if not archive_url.startswith("http"):
            archive_service.delete_file(archive_url)

    elif isinstance(report_info.raw_report, VersionOneParsedRawReport):
        # only a version 1 report needs to be "rewritten readable"

        archive_service.write_file(
            archive_url, report_info.raw_report.content().getvalue()
        )
