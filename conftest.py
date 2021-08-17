from pathlib import Path

import mock
import pytest
import vcr
from shared.config import ConfigHelper
from shared.storage.memory import MemoryStorageService
from shared.torngit import Github as GithubHandler
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy_utils import create_database, database_exists

from celery_config import initialize_logging
from database.base import Base
from database.engine import json_dumps


def pytest_configure(config):
    """
    Allows plugins and conftest files to perform initial configuration.
    This hook is called for every plugin and initial conftest
    file after command line options have been parsed.
    """
    initialize_logging()


def pytest_itemcollected(item):
    """ logic that runs on the test collection step """
    if "codecov_vcr" in item.fixturenames:
        # Tests with codecov_vcr fixtures are automatically 'integration'
        item.add_marker("integration")


@pytest.fixture(scope="session")
def engine(request, sqlalchemy_connect_url, app_config):
    """Engine configuration.
    See http://docs.sqlalchemy.org/en/latest/core/engines.html
    for more details.
    :sqlalchemy_connect_url: Connection URL to the database. E.g
    postgresql://scott:tiger@localhost:5432/mydatabase 
    :app_config: Path to a ini config file containing the sqlalchemy.url
    config variable in the DEFAULT section.
    :returns: Engine instance
    """
    if app_config:
        from sqlalchemy import engine_from_config

        engine = engine_from_config(app_config)
    elif sqlalchemy_connect_url:
        from sqlalchemy.engine import create_engine

        engine = create_engine(sqlalchemy_connect_url, json_serializer=json_dumps)
    else:
        raise RuntimeError("Can not establish a connection to the database")

    # Put a suffix like _gw0, _gw1 etc on xdist processes
    xdist_suffix = getattr(request.config, "slaveinput", {}).get("slaveid")
    if engine.url.database != ":memory:" and xdist_suffix is not None:
        engine.url.database = "{}_{}".format(engine.url.database, xdist_suffix)
        engine = create_engine(engine.url)  # override engine

    def fin():
        print("Disposing engine")
        engine.dispose()

    request.addfinalizer(fin)
    return engine


@pytest.fixture(scope="session")
def db(engine, sqlalchemy_connect_url):
    database_url = sqlalchemy_connect_url
    try:
        if not database_exists(database_url):
            create_database(database_url)
    except OperationalError:
        pytest.skip("No available db")
    connection = engine.connect()
    connection.execute("DROP SCHEMA IF EXISTS public CASCADE;")
    connection.execute("CREATE SCHEMA public;")
    Base.metadata.create_all(engine)


@pytest.fixture
def dbsession(db, engine):
    connection = engine.connect()

    connection_transaction = connection.begin()

    # bind an individual Session to the connection
    session = Session(bind=connection)

    # start the session in a SAVEPOINT...
    session.begin_nested()

    # then each time that SAVEPOINT ends, reopen it
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, transaction):
        if transaction.nested and not transaction._parent.nested:

            # ensure that state is expired the way
            # session.commit() at the top level normally does
            # (optional step)
            session.expire_all()

            session.begin_nested()

    yield session

    session.close()
    connection_transaction.rollback()
    connection.close()


@pytest.fixture
def mock_configuration(mocker):
    m = mocker.patch("shared.config._get_config_instance")
    mock_config = ConfigHelper()
    m.return_value = mock_config
    our_config = {
        "bitbucket": {"bot": {"username": "codecov-io"}},
        "services": {
            "minio": {
                "access_key_id": "codecov-default-key",
                "bucket": "archive",
                "hash_key": "88f572f4726e4971827415efa8867978",
                "periodic_callback_ms": False,
                "secret_access_key": "codecov-default-secret",
                "verify_ssl": False,
            },
            "redis_url": "redis://redis:@localhost:6379/",
        },
        "setup": {
            "codecov_url": "https://codecov.io",
            "encryption_secret": "zp^P9*i8aR3",
        },
    }
    mock_config.set_params(our_config)
    return mock_config


@pytest.fixture
def codecov_vcr(request):
    current_path = Path(request.node.fspath)
    current_path_name = current_path.name.replace(".py", "")
    cls_name = request.node.cls.__name__
    cassete_path = current_path.parent / "cassetes" / current_path_name / cls_name
    current_name = request.node.name
    casset_file_path = str(cassete_path / f"{current_name}.yaml")
    with vcr.use_cassette(
        casset_file_path,
        record_mode="once",
        filter_headers=["authorization"],
        match_on=["method", "scheme", "host", "port", "path"],
    ) as cassete_maker:
        yield cassete_maker


@pytest.fixture
def mock_redis(mocker):
    m = mocker.patch("services.redis._get_redis_instance_from_url")
    redis_server = mocker.MagicMock()
    m.return_value = redis_server
    yield redis_server


@pytest.fixture
def mock_storage(mocker):
    m = mocker.patch("services.storage._cached_get_storage_client")
    storage_server = MemoryStorageService({})
    m.return_value = storage_server
    yield storage_server


@pytest.fixture
def mock_repo_provider(mocker):
    m = mocker.patch("services.repository._get_repo_provider_service_instance")
    provider_instance = mocker.MagicMock(
        GithubHandler, get_commit_diff=mock.AsyncMock(return_value={})
    )
    m.return_value = provider_instance
    yield provider_instance


@pytest.fixture
def mock_owner_provider(mocker):
    m = mocker.patch("services.owner._get_owner_provider_service_instance")
    provider_instance = mocker.MagicMock(GithubHandler)
    m.return_value = provider_instance
    yield provider_instance


@pytest.fixture
def with_sql_functions(dbsession):
    dbsession.execute(
        """CREATE FUNCTION array_append_unique(anyarray, anyelement) RETURNS anyarray
                LANGUAGE sql IMMUTABLE
                AS $_$
            select case when $2 is null
                    then $1
                    else array_remove($1, $2) || array[$2]
                    end;
            $_$;"""
    )
    dbsession.execute(
        """create or replace function try_to_auto_activate(int, int) returns boolean as $$
            update owners
            set plan_activated_users = (
                case when coalesce(array_length(plan_activated_users, 1), 0) < plan_user_count  -- we have credits
                    then array_append_unique(plan_activated_users, $2)  -- add user
                    else plan_activated_users
                    end)
            where ownerid=$1
            returning (plan_activated_users @> array[$2]);
            $$ language sql volatile strict;"""
    )
    dbsession.execute(
        """create or replace function get_gitlab_root_group(int) returns jsonb as $$
            /* get root group by following parent_service_id to highest level */
            with recursive tree as (
                select o.service_id,
                o.parent_service_id,
                o.ownerid,
                1 as depth
                from owners o
                where o.ownerid = $1
                and o.service = 'gitlab'
                and o.parent_service_id is not null

                union all

                select o.service_id,
                o.parent_service_id,
                o.ownerid,
                depth + 1 as depth
                from tree t
                join owners o
                on o.service_id = t.parent_service_id
                /* avoid infinite loop in case of cycling (2 > 5 > 3 > 2 > 5...) up to Gitlab max subgroup depth of 20 */
                where depth <= 20
            ), data as (
                select t.ownerid,
                t.service_id
                from tree t
                where t.parent_service_id is null
            )
            select to_jsonb(data) from data limit 1;
            $$ language sql stable strict;"""
    )
    dbsession.flush()
