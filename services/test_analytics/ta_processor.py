import logging
from typing import Any

import shared.storage
from shared.django_apps.core.models import Commit
from shared.django_apps.reports.models import ReportSession
from shared.storage.exceptions import FileNotInStorageError
from test_results_parser import parse_raw_upload

from services.processing.types import UploadArguments
from services.test_analytics.ta_processing import (
    delete_archive,
    get_ta_processing_info,
    handle_file_not_found,
    handle_parsing_error,
    insert_testruns_timeseries,
    should_delete_archive,
)

log = logging.getLogger(__name__)


def ta_processor_impl(
    repoid: int,
    commitid: str,
    commit_yaml: dict[str, Any],
    argument: UploadArguments,
    update_state: bool = False,
) -> bool:
    log.info(
        "Processing single TA argument",
        extra=dict(
            upload_id=argument.get("upload_id"),
            repoid=repoid,
            commitid=commitid,
        ),
    )

    upload_id = argument.get("upload_id")
    if upload_id is None:
        return False

    upload = ReportSession.objects.get(id=upload_id)
    if upload.state == "processed":
        # don't need to process again because the intermediate result should already be in redis
        return False

    if upload.storage_path is None:
        if update_state:
            handle_file_not_found(upload)
        return False

    ta_proc_info = get_ta_processing_info(repoid, commitid, commit_yaml)

    storage_service = shared.storage.get_appropriate_storage_service(
        ta_proc_info.repository.repoid
    )

    try:
        payload_bytes = storage_service.read_file(
            ta_proc_info.bucket_name, upload.storage_path
        )
    except FileNotInStorageError:
        if update_state:
            handle_file_not_found(upload)
        return False

    try:
        parsing_infos, readable_file = parse_raw_upload(payload_bytes)
    except RuntimeError as exc:
        if update_state:
            handle_parsing_error(upload, exc)
        return False

    branch = Commit.objects.get(id=upload.report.commit_id).branch

    insert_testruns_timeseries(repoid, commitid, branch, upload, parsing_infos)

    if update_state:
        upload.state = "processed"
        upload.save()

        if should_delete_archive(ta_proc_info.user_yaml):
            delete_archive(storage_service, upload, ta_proc_info.bucket_name)
        else:
            storage_service.write_file(
                ta_proc_info.bucket_name, upload.storage_path, bytes(readable_file)
            )

    return True
