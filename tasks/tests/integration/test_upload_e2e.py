import json
from functools import partial
from typing import Iterable
from uuid import uuid4

import pytest
from redis import Redis
from shared.reports.types import ReportLine
from shared.yaml import UserYaml
from sqlalchemy.orm import Session

from database.tests.factories import CommitFactory, RepositoryFactory
from rollouts import PARALLEL_UPLOAD_PROCESSING_BY_REPO
from services.archive import ArchiveService
from services.redis import get_redis_connection
from services.report import ReportService
from tasks.tests.utils import hook_repo_provider, hook_session, run_tasks
from tasks.upload import upload_task


def write_raw_upload(
    redis: Redis,
    archive_service: ArchiveService,
    repoid: int,
    commitid: str,
    contents: bytes,
):
    report_id = uuid4().hex
    written_path = archive_service.write_raw_upload(commitid, report_id, contents)
    upload = json.dumps({"reportid": report_id, "url": written_path})

    redis_key = f"uploads/{repoid}/{commitid}"
    redis.lpush(redis_key, upload)


def lines(lines: Iterable[tuple[int, ReportLine]]) -> list[tuple[int, int]]:
    return list(((lineno, line.coverage) for lineno, line in lines))


@pytest.mark.integration
@pytest.mark.django_db()
@pytest.mark.parametrize("do_parallel_processing", [False, True])
def test_full_upload(
    dbsession: Session,
    do_parallel_processing: bool,
    mocker,
    mock_repo_provider,
    mock_storage,
    mock_configuration,
):
    # patch various `get_db_session` imports
    hook_session(mocker, dbsession)
    # to not close the session after each task
    mocker.patch("tasks.base.BaseCodecovTask.wrap_up_dbsession")
    # patch various `get_repo_provider_service` imports
    hook_repo_provider(mocker, mock_repo_provider)
    # avoid some calls reaching out to git providers
    mocker.patch("tasks.upload.UploadTask.possibly_setup_webhooks", return_value=True)
    mocker.patch(
        "tasks.upload.fetch_commit_yaml_and_possibly_store", return_value=UserYaml({})
    )
    # force `report_json` to be written out to storage
    mock_configuration.set_params(
        {
            "setup": {
                "save_report_data_in_storage": {
                    "commit_report": "general_access",
                    "report_details_files_array": "general_access",
                },
            }
        }
    )
    # use parallel processing:
    mocker.patch.object(
        PARALLEL_UPLOAD_PROCESSING_BY_REPO,
        "check_value",
        return_value=do_parallel_processing,
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    repoid = repository.repoid
    commitid = uuid4().hex
    commit = CommitFactory.create(repository=repository, commitid=commitid)
    dbsession.add(commit)
    dbsession.flush()

    archive_service = ArchiveService(repository)
    do_upload = partial(
        write_raw_upload,
        get_redis_connection(),
        archive_service,
        repoid,
        commitid,
    )

    do_upload(b"""
a.rs
<<<<<< network
# path=coverage.lcov
SF:a.rs
DA:1,1
end_of_record
""")
    do_upload(b"""
a.rs
<<<<<< network
# path=coverage.lcov
SF:a.rs
DA:2,2
end_of_record
""")
    do_upload(b"""
b.rs
<<<<<< network
# path=coverage.lcov
SF:b.rs
DA:1,3
end_of_record
""")
    do_upload(b"""
b.rs
<<<<<< network
# path=coverage.lcov
SF:b.rs
DA:2,5
end_of_record
""")

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )

    report_service = ReportService(UserYaml({}))
    report = report_service.get_existing_report_for_commit(commit, report_code=None)

    assert report
    assert set(report.files) == set(("a.rs", "b.rs"))

    a = report.get("a.rs")
    assert a
    assert lines(a.lines) == [
        (1, 1),
        (2, 2),
    ]

    b = report.get("b.rs")
    assert b
    assert lines(b.lines) == [(1, 3), (2, 5)]

    # Adding one more upload

    do_upload(b"""
c.rs
<<<<<< network
# path=coverage.lcov
SF:c.rs
DA:2,4
end_of_record
""")

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )

    report = report_service.get_existing_report_for_commit(commit, report_code=None)

    assert report
    assert set(report.files) == set(("a.rs", "b.rs", "c.rs"))

    c = report.get("c.rs")
    assert c
    assert lines(c.lines) == [(2, 4)]  # only yields covered lines

    archive = mock_storage.storage["archive"]
    repo_hash = ArchiveService.get_archive_hash(repository)
    raw_chunks_path = f"v4/repos/{repo_hash}/commits/{commitid}/chunks.txt"
    assert raw_chunks_path in archive
    raw_files_sessions_path = f"v4/repos/{repo_hash}/commits/{commitid}/json_data/commits/report_json/{commitid}.json"
    assert raw_files_sessions_path in archive
