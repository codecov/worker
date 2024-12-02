import asyncio

from asgiref.sync import async_to_sync
from sqlalchemy.exc import IntegrityError

from database.tests.factories.core import CommitFactory, OwnerFactory, RepositoryFactory
from helpers.log_context import LogContext, get_log_context, set_log_context


def create_db_records(dbsession):
    owner = OwnerFactory.create(
        service="github",
        username="codecove2e",
        unencrypted_oauth_token="test76zow6xgh7modd88noxr245j2z25t4ustoff",
        plan="users-basic",
    )
    dbsession.add(owner)

    repo = RepositoryFactory.create(
        owner=owner,
        yaml={"codecov": {"max_report_age": "1y ago"}},
        name="example-python",
    )
    dbsession.add(repo)

    commit = CommitFactory.create(
        message="",
        commitid="c5b67303452bbff57cc1f49984339cde39eb1db5",
        repository=repo,
    )
    dbsession.add(commit)

    dbsession.commit()
    dbsession.expire(owner)
    dbsession.expire(repo)
    dbsession.expire(commit)

    return owner, repo, commit


def test_populate_just_owner(dbsession):
    owner, _repo, _commit = create_db_records(dbsession)
    log_context = LogContext(owner_id=owner.ownerid)
    log_context.populate_from_sqlalchemy(dbsession)

    assert log_context == LogContext(
        owner_id=owner.ownerid,
        owner_username="codecove2e",
        owner_service="github",
        owner_plan="users-basic",
    )


def test_populate_just_repo(dbsession):
    owner, repo, _commit = create_db_records(dbsession)
    log_context = LogContext(repo_id=repo.repoid)
    log_context.populate_from_sqlalchemy(dbsession)

    assert log_context == LogContext(
        repo_id=repo.repoid,
        repo_name="example-python",
        owner_id=owner.ownerid,
        owner_username="codecove2e",
        owner_service="github",
        owner_plan="users-basic",
    )


def test_populate_just_commit_sha(dbsession):
    _owner, _repo, commit = create_db_records(dbsession)
    log_context = LogContext(commit_sha=commit.commitid)
    log_context.populate_from_sqlalchemy(dbsession)

    assert log_context == LogContext(commit_sha=commit.commitid)


def test_populate_just_commit_id(dbsession):
    owner, repo, commit = create_db_records(dbsession)
    log_context = LogContext(commit_id=commit.id_)
    log_context.populate_from_sqlalchemy(dbsession)

    assert log_context == LogContext(
        repo_id=repo.repoid,
        repo_name="example-python",
        owner_id=owner.ownerid,
        owner_username="codecove2e",
        owner_service="github",
        owner_plan="users-basic",
        commit_sha=commit.commitid,
        commit_id=commit.id_,
    )


def test_populate_repo_and_commit_sha(dbsession):
    owner, repo, commit = create_db_records(dbsession)
    log_context = LogContext(repo_id=repo.repoid, commit_sha=commit.commitid)
    log_context.populate_from_sqlalchemy(dbsession)

    assert log_context == LogContext(
        repo_id=repo.repoid,
        repo_name="example-python",
        owner_id=owner.ownerid,
        owner_username="codecove2e",
        owner_service="github",
        owner_plan="users-basic",
        commit_sha=commit.commitid,
        commit_id=commit.id_,
    )


def test_populate_ignores_db_exceptions(dbsession, mocker):
    owner, repo, commit = create_db_records(dbsession)
    log_context = LogContext(repo_id=repo.repoid, commit_sha=commit.commitid)
    mocker.patch.object(dbsession, "query", side_effect=IntegrityError("", {}, None))

    # If this succeeds, the exception thrown by dbsession was ignored
    log_context.populate_from_sqlalchemy(dbsession)


def test_set_and_get_log_context(dbsession):
    log_context = LogContext(repo_id=1, commit_sha="abcde", commit_id=2, owner_id=3)
    set_log_context(log_context)

    assert get_log_context() == log_context

    async def check_context_in_coroutine():
        coro_log_context = get_log_context()
        assert coro_log_context == log_context

    # Check that the ContextVar is propagated through multiple ways of running
    # async functions
    asyncio.run(check_context_in_coroutine())
    async_to_sync(check_context_in_coroutine)()


def test_as_dict(dbsession, mocker):
    owner, repo, commit = create_db_records(dbsession)
    log_context = LogContext(commit_id=commit.id_, task_name="foo", task_id="bar")
    log_context.populate_from_sqlalchemy(dbsession)

    mock_span = mocker.Mock()
    mock_span.trace_id = 123
    mocker.patch("helpers.log_context.get_current_span", return_value=mock_span)

    # `_populated_from_db` is a dataclass field that we want to strip
    # `sentry_trace_id` is a property that we want to include
    assert log_context.as_dict() == {
        "task_name": "foo",
        "task_id": "bar",
        "commit_id": commit.id_,
        "commit_sha": commit.commitid,
        "repo_id": repo.repoid,
        "repo_name": repo.name,
        "owner_id": owner.ownerid,
        "owner_username": owner.username,
        "owner_service": owner.service,
        "owner_plan": owner.plan,
        "sentry_trace_id": 123,
        "checkpoints_data": {},
    }


def test_add_to_log_record(dbsession):
    owner, repo, commit = create_db_records(dbsession)
    log_context = LogContext(commit_id=commit.id_, task_name="foo", task_id="bar")
    log_context.populate_from_sqlalchemy(dbsession)

    log_record = {}
    log_context.add_to_log_record(log_record)

    expected_dict = log_context.as_dict()
    expected_dict.pop("checkpoints_data", None)
    assert log_record["context"] == expected_dict


def test_add_to_sentry(dbsession, mocker):
    mock_set_tags = mocker.patch("sentry_sdk.set_tags")

    owner, repo, commit = create_db_records(dbsession)
    log_context = LogContext(commit_id=commit.id_, task_name="foo", task_id="bar")
    log_context.populate_from_sqlalchemy(dbsession)

    # Calls `log_context.set_to_sentry()`
    set_log_context(log_context)

    expected_sentry_fields = log_context.as_dict()
    expected_sentry_fields.pop("sentry_trace_id")
    expected_sentry_fields.pop("checkpoints_data")
    mock_set_tags.assert_called_with(expected_sentry_fields)
