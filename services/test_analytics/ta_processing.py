from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import sentry_sdk
import test_results_parser
from shared.config import get_config
from shared.django_apps.core.models import Commit, Repository
from shared.django_apps.reports.models import ReportSession, UploadError
from shared.storage.base import BaseStorageService

from services.test_analytics.ta_timeseries import get_flaky_tests_set, insert_testrun
from services.yaml import UserYaml, read_yaml_field


@dataclass
class TAProcInfo:
    repository: Repository
    branch: str | None
    bucket_name: str
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

    bucket_name = cast(
        str, get_config("services", "minio", "bucket", default="archive")
    )
    user_yaml: UserYaml = UserYaml(commit_yaml)
    return TAProcInfo(
        repository,
        branch,
        bucket_name,
        user_yaml,
    )


def should_delete_archive(user_yaml: UserYaml) -> bool:
    if get_config("services", "minio", "expire_raw_after_n_days"):
        return True
    return not read_yaml_field(user_yaml, ("codecov", "archive", "uploads"), _else=True)


def delete_archive(
    storage_service: BaseStorageService, upload: ReportSession, bucket_name: str
):
    archive_url = upload.storage_path
    if archive_url and not archive_url.startswith("http"):
        storage_service.delete_file(bucket_name, archive_url)


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
