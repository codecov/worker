import logging
import os
from pathlib import Path

import mock
import pytest
import vcr
from shared.config import ConfigHelper
from shared.storage.memory import MemoryStorageService
from shared.torngit import Github as GithubHandler
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy_utils import database_exists

from celery_config import initialize_logging
from database.base import Base
from database.engine import json_dumps
from helpers.environment import _get_cached_current_env


# @pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """
    Allows plugins and conftest files to perform initial configuration.
    This hook is called for every plugin and initial conftest
    file after command line options have been parsed.
    """
    os.environ["CURRENT_ENVIRONMENT"] = "local"
    os.environ["RUN_ENV"] = "DEV"
    _get_cached_current_env.cache_clear()
    initialize_logging()


def pytest_itemcollected(item):
    """logic that runs on the test collection step"""
    if "codecov_vcr" in item.fixturenames:
        # Tests with codecov_vcr fixtures are automatically 'integration'
        item.add_marker("integration")


@pytest.fixture(scope="session")
def engine(request, sqlalchemy_db, sqlalchemy_connect_url, app_config):
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

    # Check that the DB exist and migrate the unmigrated SQLALchemy models as a stop-gap
    database_url = sqlalchemy_connect_url
    if not database_exists(database_url):
        raise RuntimeError(f"SQLAlchemy cannot connect to DB at {database_url}")

    Base.metadata.tables["profiling_profilingcommit"].create(
        bind=engine, checkfirst=True
    )
    Base.metadata.tables["profiling_profilingupload"].create(
        bind=engine, checkfirst=True
    )
    Base.metadata.tables["timeseries_measurement"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["timeseries_dataset"].create(bind=engine, checkfirst=True)

    Base.metadata.tables["compare_commitcomparison"].create(
        bind=engine, checkfirst=True
    )
    Base.metadata.tables["compare_flagcomparison"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["compare_componentcomparison"].create(
        bind=engine, checkfirst=True
    )

    Base.metadata.tables["labelanalysis_labelanalysisrequest"].create(
        bind=engine, checkfirst=True
    )
    Base.metadata.tables["labelanalysis_labelanalysisprocessingerror"].create(
        bind=engine, checkfirst=True
    )

    Base.metadata.tables["staticanalysis_staticanalysissuite"].create(
        bind=engine, checkfirst=True
    )
    Base.metadata.tables["staticanalysis_staticanalysissinglefilesnapshot"].create(
        bind=engine, checkfirst=True
    )
    Base.metadata.tables["staticanalysis_staticanalysissuitefilepath"].create(
        bind=engine, checkfirst=True
    )

    yield engine

    print("Disposing engine")  # noqa: T201
    engine.dispose()


@pytest.fixture(scope="session")
def sqlalchemy_db(request: pytest.FixtureRequest, django_db_blocker, django_db_setup):
    # Bootstrap the DB by running the Django bootstrap version.
    from django.conf import settings
    from django.db import connections
    from django.test.utils import setup_databases, teardown_databases

    keepdb = request.config.getvalue("reuse_db", False) and not request.config.getvalue(
        "create_db", False
    )

    with django_db_blocker.unblock():
        # Temporarily reset the database to the SQLAlchemy DBs to run the migrations.
        original_db_name = settings.DATABASES["default"]["NAME"]
        original_test_name = settings.DATABASES["default"]["TEST"]["NAME"]
        settings.DATABASES["default"]["NAME"] = "sqlalchemy"
        settings.DATABASES["default"]["TEST"]["NAME"] = "test_postgres_sqlalchemy"
        db_cfg = setup_databases(
            verbosity=request.config.option.verbose,
            interactive=False,
            keepdb=keepdb,
        )
        settings.DATABASES["default"]["NAME"] = original_db_name
        settings.DATABASES["default"]["TEST"]["NAME"] = original_test_name

        # Hack to get the default connection for the test database to _actually_ be the
        # Django database that the django_db should actually use. It was set to the SQLAlchemy database,
        # but this makes sure that the default Django DB connection goes to the Django database.
        # Since the database was already created and migrated in the django_db_setup fixture,
        # we set keepdb=True to avoid recreating the database and rerunning the migrations.
        connections.configure_settings(settings.DATABASES)
        connections["default"].creation.create_test_db(
            verbosity=request.config.option.verbose,
            autoclobber=True,
            keepdb=True,
        )

    yield

    if not keepdb:
        try:
            with django_db_blocker.unblock():
                # Need to set `test_postgres_sqlalchemy` as the main db name to tear down properly.
                settings.DATABASES["default"]["NAME"] = "test_postgres_sqlalchemy"
                teardown_databases(db_cfg, verbosity=request.config.option.verbose)
                settings.DATABASES["default"]["NAME"] = original_db_name
        except Exception as exc:  # noqa: BLE001
            request.node.warn(
                pytest.PytestWarning(
                    f"Error when trying to teardown test databases: {exc!r}"
                )
            )


@pytest.fixture
def dbsession(sqlalchemy_db, engine):
    """Sets up the SQLAlchemy dbsession."""
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
                "secret_access_key": "codecov-default-secret",
                "verify_ssl": False,
            },
            "smtp": {
                "host": "mailhog",
                "port": 1025,
                "username": "username",
                "password": "password",
            },
        },
        "setup": {
            "codecov_url": "https://codecov.io",
            "encryption_secret": "zp^P9*i8aR3",
            "telemetry": {
                "endpoint_override": "abcde",
            },
        },
    }
    mock_config.set_params(our_config)
    return mock_config


@pytest.fixture
def empty_configuration(mocker):
    m = mocker.patch("shared.config._get_config_instance")
    mock_config = ConfigHelper()
    m.return_value = mock_config
    return mock_config


@pytest.fixture
def codecov_vcr(request):
    vcr_log = logging.getLogger("vcr")
    vcr_log.setLevel(logging.ERROR)

    current_path = Path(request.node.fspath)
    current_path_name = current_path.name.replace(".py", "")
    cassete_path = current_path.parent / "cassetes" / current_path_name
    if request.node.cls:
        cls_name = request.node.cls.__name__
        cassete_path = cassete_path / cls_name
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
    m = mocker.patch("shared.storage.get_appropriate_storage_service")
    storage_server = MemoryStorageService({})
    m.return_value = storage_server
    return storage_server


@pytest.fixture
def mock_archive_storage(mocker):
    mocker.patch(
        "shared.django_apps.core.models.should_write_data_to_storage_config_check",
        return_value=True,
    )
    storage_server = MemoryStorageService({})
    mocker.patch(
        "shared.api_archive.archive.StorageService", return_value=storage_server
    )
    mocker.patch(
        "shared.storage.get_appropriate_storage_service", return_value=storage_server
    )
    return storage_server


@pytest.fixture
def mock_smtp(mocker):
    m = mocker.patch("services.smtp.SMTPService")
    smtp_server = mocker.MagicMock()
    m.return_value = smtp_server
    yield smtp_server


@pytest.fixture
def mock_repo_provider(mocker):
    m = mocker.patch("services.repository._get_repo_provider_service_instance")
    provider_instance = mocker.MagicMock(
        GithubHandler,
        data={},
        get_commit_diff=mock.AsyncMock(return_value={}),
        get_distance_in_commits=mock.AsyncMock(
            return_value={"behind_by": 0, "behind_by_commit": None}
        ),
    )
    m.return_value = provider_instance
    yield provider_instance


@pytest.fixture
def mock_owner_provider(mocker):
    provider_instance = mocker.MagicMock(GithubHandler)

    def side_effect(*args, **kwargs):
        provider_instance.data = {**kwargs}
        return provider_instance

    m = mocker.patch("services.owner._get_owner_provider_service_instance")
    m.side_effect = side_effect
    yield provider_instance


@pytest.fixture
def with_sql_functions(dbsession):
    dbsession.execute(
        """CREATE OR REPLACE FUNCTION array_append_unique(anyarray, anyelement) RETURNS anyarray
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


# We don't want any tests submitting checkpoint logs to Sentry for real
@pytest.fixture(autouse=True)
def mock_checkpoint_submit(mocker, request):
    # We mock sentry differently in the tests for CheckpointLogger
    if request.node.get_closest_marker("real_checkpoint_logger"):
        return

    def mock_submit_fn(metric, start, end, data={}):
        pass

    mock_submit = mocker.Mock()
    mock_submit.side_effect = mock_submit_fn

    return mocker.patch(
        "helpers.checkpoint_logger.BaseFlow.submit_subflow", mock_submit
    )


@pytest.fixture(autouse=True)
def mock_feature(mocker, request):
    if request.node.get_closest_marker("real_feature"):
        return

    from shared.rollouts import Feature

    def check_value(self, identifier, default=False):
        return default

    return mocker.patch.object(Feature, "check_value", check_value)
