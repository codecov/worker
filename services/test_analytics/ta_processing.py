from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sentry_sdk
import test_results_parser
from shared.config import get_config
from shared.django_apps.core.models import Commit, Repository
from shared.django_apps.reports.models import ReportSession, UploadError

from services.archive import ArchiveService
from services.test_analytics.ta_timeseries import get_flaky_tests_set, insert_testrun
from services.yaml import UserYaml, read_yaml_field


@dataclass
class TAProcInfo:
    repository: Repository
    branch: str | None
    user_yaml: UserYaml


def handle_file_not_found(upload: ReportSession):
    upload.state = "processed"
    upload.save()
    UploadError.objects.create(
        report_session=upload,
        error_code="file_not_in_storage",
        error_params={},
    )


def handle_parsing_error(upload: ReportSession, exc: Exception):
    sentry_sdk.capture_exception(exc, tags={"upload_state": upload.state})
    upload.state = "processed"
    upload.save()
    UploadError.objects.create(
        report_session=upload,
        error_code="unsupported_file_format",
        error_params={"error_message": str(exc)},
    )


def get_ta_processing_info(
    repoid: int,
    commitid: str,
    commit_yaml: dict[str, Any],
) -> TAProcInfo:
    repository = Repository.objects.get(repoid=repoid)

    commit = Commit.objects.get(repository=repository, commitid=commitid)
    branch = commit.branch
    if branch is None:
        raise ValueError("Branch is None")

    user_yaml: UserYaml = UserYaml(commit_yaml)
    return TAProcInfo(
        repository,
        branch,
        user_yaml,
    )


def should_delete_archive_settings(user_yaml: UserYaml) -> bool:
    if get_config("services", "minio", "expire_raw_after_n_days"):
        return True
    return not read_yaml_field(user_yaml, ("codecov", "archive", "uploads"), _else=True)


def rewrite_or_delete_upload(
    archive_service: ArchiveService,
    user_yaml: UserYaml,
    upload: ReportSession,
    readable_file: bytes,
):
    if should_delete_archive_settings(user_yaml):
        archive_url = upload.storage_path
        if archive_url and not archive_url.startswith("http"):
            archive_service.delete_file(archive_url)
    else:
        archive_service.write_file(upload.storage_path, bytes(readable_file))


def insert_testruns_timeseries(
    repoid: int,
    commitid: str,
    branch: str | None,
    upload: ReportSession,
    parsing_infos: list[test_results_parser.ParsingInfo],
):
    flaky_test_set = get_flaky_tests_set(repoid)

    for parsing_info in parsing_infos:
        insert_testrun(
            timestamp=upload.created_at,
            repo_id=repoid,
            commit_sha=commitid,
            branch=branch,
            upload_id=upload.id,
            flags=upload.flag_names,
            parsing_info=parsing_info,
            flaky_test_ids=flaky_test_set,
        )
