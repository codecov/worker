import json
import random
from functools import partial
from typing import Iterable
from uuid import uuid4

import pytest
from redis import Redis
from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from shared.utils.sessions import SessionType
from shared.yaml import UserYaml
from sqlalchemy.orm import Session as DbSession

from database.models.core import Commit, CompareCommit, Repository
from database.models.reports import Upload
from database.tests.factories import CommitFactory, RepositoryFactory
from database.tests.factories.core import PullFactory
from rollouts import INTERMEDIATE_REPORTS_IN_REDIS
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
    upload_json: dict | None = None,
):
    report_id = uuid4().hex
    written_path = archive_service.write_raw_upload(commitid, report_id, contents)

    upload_json = upload_json or {}
    upload_json.update({"reportid": report_id, "url": written_path})
    upload = json.dumps(upload_json)

    redis_key = f"uploads/{repoid}/{commitid}"
    redis.lpush(redis_key, upload)

    return upload_json


def lines(lines: Iterable[tuple[int, ReportLine]]) -> list[tuple[int, int]]:
    return list(((lineno, line.coverage) for lineno, line in lines))


def get_base_report():
    file_a = ReportFile("a.rs")
    file_a.append(1, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    file_a.append(1, ReportLine.create(coverage=2, sessions=[[1, 2]]))

    file_b = ReportFile("b.rs")
    file_b.append(1, ReportLine.create(coverage=3, sessions=[[0, 3]]))
    file_b.append(2, ReportLine.create(coverage=5, sessions=[[1, 5]]))
    report = Report()
    report.append(file_a)
    report.append(file_b)
    return report


def setup_base_commit(repository: Repository, dbsession: DbSession) -> Commit:
    base_report = get_base_report()
    commit = CommitFactory(repository=repository)
    dbsession.add(commit)
    dbsession.flush()
    report_service = ReportService({})
    report_service.save_full_report(commit, base_report)
    return commit


def setup_mock_get_compare(
    base_commit: Commit, head_commit: Commit, mock_repo_provider
):
    get_compare = {
        "diff": {
            "files": {
                "a.rs": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["1", "3", "1", "4"],
                            "lines": [
                                " fn main() {",
                                '-   println!("Salve!");',
                                '+   println!("Hello World!");',
                                '+   println!(":wink:");',
                                " }",
                            ],
                        }
                    ],
                }
            }
        },
        "commits": [
            {
                "commitid": base_commit.commitid,
                "message": "BASE commit",
                "timestamp": base_commit.timestamp,
                "author": {
                    "id": base_commit.author.service_id,
                    "username": base_commit.author.username,
                },
            },
            {
                "commitid": head_commit.commitid,
                "message": "HEAD commit",
                "timestamp": head_commit.timestamp,
                "author": {
                    "id": head_commit.author.service_id,
                    "username": head_commit.author.username,
                },
            },
        ],
    }
    mock_repo_provider.get_compare.return_value = get_compare


def setup_mocks(
    mocker,
    dbsession: DbSession,
    mock_configuration,
    mock_repo_provider,
    user_yaml=None,
):
    # patch various `get_db_session` imports
    hook_session(mocker, dbsession)
    # to not close the session after each task
    mocker.patch("tasks.base.BaseCodecovTask.wrap_up_dbsession")
    mocker.patch("tasks.base.BaseCodecovTask._commit_django")
    # patch various `get_repo_provider_service` imports
    hook_repo_provider(mocker, mock_repo_provider)
    # avoid some calls reaching out to git providers
    mocker.patch("tasks.upload.UploadTask.possibly_setup_webhooks", return_value=True)
    mocker.patch(
        "tasks.upload.fetch_commit_yaml_and_possibly_store",
        return_value=UserYaml(user_yaml or {}),
    )
    # disable all the tasks being emitted from `UploadFinisher`.
    # ideally, we would really want to test their outcomes as well.
    mocker.patch("tasks.notify.NotifyTask.run_impl")
    mocker.patch("tasks.save_commit_measurements.SaveCommitMeasurementsTask.run_impl")

    # force `report_json` to be written out to storage
    mock_configuration.set_params(
        {
            "setup": {
                "save_report_data_in_storage": {
                    "commit_report": "general_access",
                },
            }
        }
    )


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize("redis_storage", [True, False])
def test_full_upload(
    dbsession: DbSession,
    redis_storage: bool,
    mocker,
    mock_repo_provider,
    mock_storage,
    mock_configuration,
):
    setup_mocks(mocker, dbsession, mock_configuration, mock_repo_provider)

    mocker.patch.object(
        INTERMEDIATE_REPORTS_IN_REDIS,
        "check_value",
        return_value=redis_storage,
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    # setup a base commit (with a report) to compare against the current one
    base_commit = setup_base_commit(repository, dbsession)

    repoid = repository.repoid
    commitid = uuid4().hex
    # BASE and HEAD are connected in a PR
    pull = PullFactory(
        pullid=12,
        repository=repository,
        compared_to=base_commit.commitid,
    )
    commit = CommitFactory.create(
        repository=repository, commitid=commitid, pullid=12, _report_json=None
    )
    dbsession.add(pull)
    dbsession.flush()

    dbsession.add(commit)
    dbsession.flush()

    setup_mock_get_compare(base_commit, commit, mock_repo_provider)

    archive_service = ArchiveService(repository)
    do_upload = partial(
        write_raw_upload,
        get_redis_connection(),
        archive_service,
        repoid,
        commitid,
    )

    report_service = ReportService({})
    commit_report = report_service.initialize_and_save_report(commit)

    upload_id = 2**33 + int(random.random() * 2**15)

    first_upload_json = do_upload(
        b"""
a.rs
<<<<<< network
# path=coverage.lcov
SF:a.rs
DA:1,1
end_of_record
""",
        {"upload_id": upload_id},
    )

    first_upload = report_service.create_report_upload(first_upload_json, commit_report)
    first_upload.flags = []
    dbsession.flush()

    # force the upload to have a really high ID:
    dbsession.execute(
        f"UPDATE reports_upload SET id={upload_id} WHERE id={first_upload.id}"
    )

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )

    do_upload(
        b"""
a.rs
<<<<<< network
# path=coverage.lcov
SF:a.rs
DA:2,2
DA:3,1
end_of_record
"""
    )
    do_upload(
        b"""
b.rs
<<<<<< network
# path=coverage.lcov
SF:b.rs
DA:1,3
end_of_record
"""
    )
    do_upload(
        b"""
b.rs
<<<<<< network
# path=coverage.lcov
SF:b.rs
DA:2,5
end_of_record
"""
    )

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )

    # we expect the following files:
    # chunks+json for the base commit
    # 4 * raw uploads
    # chunks+json, and `comparison` for the finished upload
    archive = mock_storage.storage["archive"]
    assert len(archive) == 2 + 4 + 3

    report_service = ReportService(UserYaml({}))
    report = report_service.get_existing_report_for_commit(commit, report_code=None)

    assert report
    assert set(report.files) == {"a.rs", "b.rs"}

    a = report.get("a.rs")
    assert a
    assert lines(a.lines) == [
        (1, 1),
        (2, 2),
        (3, 1),
    ]

    b = report.get("b.rs")
    assert b
    assert lines(b.lines) == [
        (1, 3),
        (2, 5),
    ]

    # Adding one more upload

    do_upload(
        b"""
c.rs
<<<<<< network
# path=coverage.lcov
SF:c.rs
DA:2,4
end_of_record
"""
    )

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )

    report = report_service.get_existing_report_for_commit(commit, report_code=None)

    assert report
    assert set(report.files) == {"a.rs", "b.rs", "c.rs"}

    c = report.get("c.rs")
    assert c
    assert lines(c.lines) == [
        (2, 4),
    ]

    assert len(archive) == 2 + 5 + 3
    repo_hash = ArchiveService.get_archive_hash(repository)
    raw_chunks_path = f"v4/repos/{repo_hash}/commits/{commitid}/chunks.txt"
    assert raw_chunks_path in archive
    raw_files_sessions_path = f"v4/repos/{repo_hash}/commits/{commitid}/json_data/commits/report_json/{commitid}.json"
    assert raw_files_sessions_path in archive

    comparison: CompareCommit = (
        dbsession.query(CompareCommit)
        .filter(
            CompareCommit.base_commit_id == base_commit.id,
            CompareCommit.compare_commit_id == commit.id,
        )
        .first()
    )
    assert comparison is not None
    assert comparison.error is None
    assert comparison.state == "processed"
    assert comparison.patch_totals == {
        "hits": 2,
        "misses": 0,
        "coverage": 1,
        "partials": 0,
    }


@pytest.mark.integration
@pytest.mark.django_db()
@pytest.mark.parametrize("redis_storage", [True, False])
def test_full_carryforward(
    dbsession: DbSession,
    redis_storage: bool,
    mocker,
    mock_repo_provider,
    mock_storage,
    mock_configuration,
):
    user_yaml = {"flag_management": {"default_rules": {"carryforward": True}}}
    setup_mocks(
        mocker, dbsession, mock_configuration, mock_repo_provider, user_yaml=user_yaml
    )
    mocker.patch("tasks.compute_comparison.ComputeComparisonTask.run_impl")

    mocker.patch.object(
        INTERMEDIATE_REPORTS_IN_REDIS,
        "check_value",
        return_value=redis_storage,
    )

    repository = RepositoryFactory.create()
    dbsession.add(repository)
    dbsession.flush()

    repoid = repository.repoid
    commitid = uuid4().hex
    base_commit = CommitFactory.create(repository=repository, commitid=commitid)
    dbsession.add(base_commit)
    dbsession.flush()

    archive_service = ArchiveService(repository)
    do_upload = partial(
        write_raw_upload,
        get_redis_connection(),
        archive_service,
        repoid,
        commitid,
    )

    do_upload(
        b"""
a.rs
<<<<<< network
# path=coverage.lcov
SF:a.rs
DA:1,1
end_of_record
""",
        {"flags": "a"},
    )
    do_upload(
        b"""
a.rs
<<<<<< network
# path=coverage.lcov
SF:a.rs
DA:2,2
DA:3,1
end_of_record
""",
        {"flags": "a"},
    )
    do_upload(
        b"""
b.rs
<<<<<< network
# path=coverage.lcov
SF:b.rs
DA:1,3
end_of_record
""",
        {"flags": "b"},
    )
    do_upload(
        b"""
b.rs
<<<<<< network
# path=coverage.lcov
SF:b.rs
DA:2,5
end_of_record
""",
        {"flags": "b"},
    )

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )

    report_service = ReportService(UserYaml({}))
    report = report_service.get_existing_report_for_commit(
        base_commit, report_code=None
    )
    assert report

    base_sessions = report.sessions

    assert set(report.files) == {"a.rs", "b.rs"}

    a = report.get("a.rs")
    assert a
    assert lines(a.lines) == [
        (1, 1),
        (2, 2),
        (3, 1),
    ]

    b = report.get("b.rs")
    assert b
    assert lines(b.lines) == [
        (1, 3),
        (2, 5),
    ]

    # Then, upload only *half* of the reports using carry-forward logic:

    commitid = uuid4().hex
    commit = CommitFactory.create(
        repository=repository,
        commitid=commitid,
        _report_json=None,
        parent_commit_id=base_commit.commitid,
    )
    dbsession.add(commit)
    dbsession.flush()

    # BASE and HEAD are connected in a PR
    pull = PullFactory(
        pullid=12,
        repository=repository,
        compared_to=base_commit.commitid,
    )
    dbsession.add(pull)
    dbsession.flush()
    setup_mock_get_compare(base_commit, commit, mock_repo_provider)

    do_upload = partial(
        write_raw_upload,
        get_redis_connection(),
        archive_service,
        repoid,
        commitid,
    )

    do_upload(
        b"""
a.rs
<<<<<< network
# path=coverage.lcov
SF:a.rs
DA:1,1
end_of_record
""",
        {"flags": "a"},
    )

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )

    # with only one upload being processed so far, we still expect all "b" sessions to still exist
    report = report_service.get_existing_report_for_commit(commit, report_code=None)

    assert report
    assert set(report.files) == {"a.rs", "b.rs"}

    a = report.get("a.rs")
    assert a
    assert lines(a.lines) == [
        (1, 1),
    ]

    b = report.get("b.rs")
    assert b
    assert lines(b.lines) == [
        (1, 3),
        (2, 5),
    ]

    sessions = report.sessions
    # we expect there to be a total of 3 sessions, two of which are carriedforward
    assert len(sessions) == 3
    carriedforward_sessions = sum(
        1 for s in sessions.values() if s.session_type == SessionType.carriedforward
    )
    assert carriedforward_sessions == 2

    # the `Upload`s in the database should match the `sessions` in the report:
    uploads = (
        dbsession.query(Upload).filter(Upload.report_id == commit.report.id_).all()
    )
    assert {upload.order_number for upload in uploads} == {
        session.id for session in sessions.values()
    }

    # and then overwrite data related to "b" as well
    do_upload(
        b"""
b.rs
<<<<<< network
# path=coverage.lcov
SF:b.rs
DA:1,3
end_of_record
""",
        {"flags": "b"},
    )

    with run_tasks():
        upload_task.apply_async(
            kwargs={
                "repoid": repoid,
                "commitid": commitid,
            }
        )
    report = report_service.get_existing_report_for_commit(commit, report_code=None)

    assert report
    assert set(report.files) == {"a.rs", "b.rs"}

    a = report.get("a.rs")
    assert a
    assert lines(a.lines) == [
        (1, 1),
    ]

    b = report.get("b.rs")
    assert b
    assert lines(b.lines) == [
        (1, 3),
    ]

    assert len(report.sessions) == 2
    uploads = (
        dbsession.query(Upload).filter(Upload.report_id == commit.report.id_).all()
    )
    assert {upload.order_number for upload in uploads} == {
        session.id for session in report.sessions.values()
    }

    # just as a sanity check: any cleanup for the followup commit did not touch
    # data of the base commit:
    uploads = (
        dbsession.query(Upload).filter(Upload.report_id == base_commit.report.id_).all()
    )
    assert {upload.order_number for upload in uploads} == {
        session.id for session in base_sessions.values()
    }

    # we expect the following files:
    # chunks+json for the base commit
    # 6 * raw uploads
    # chunks+json for the carryforwarded commit (no `comparison`)
    archive = mock_storage.storage["archive"]
    assert len(archive) == 2 + 6 + 2
