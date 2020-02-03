from sqlalchemy.orm import Session

from pathlib import Path
from asyncio import Future

import pytest
import vcr
from sqlalchemy.exc import OperationalError
from sqlalchemy import event

from database.base import Base
from database.engine import json_dumps
from sqlalchemy_utils import create_database, database_exists
from covreports.config import ConfigHelper
from covreports.storage.memory import MemoryStorageService
from celery_config import initialize_logging


def pytest_configure(config):
    """
    Allows plugins and conftest files to perform initial configuration.
    This hook is called for every plugin and initial conftest
    file after command line options have been parsed.
    """
    initialize_logging()


def pytest_itemcollected(item):
    """ logic that runs on the test collection step """
    if 'codecov_vcr' in item.fixturenames:
        # Tests with codecov_vcr fixtures are automatically 'integration'
        item.add_marker('integration')


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
    xdist_suffix = getattr(request.config, 'slaveinput', {}).get('slaveid')
    if engine.url.database != ':memory:' and xdist_suffix is not None:
        engine.url.database = '{}_{}'.format(engine.url.database, xdist_suffix)
        engine = create_engine(engine.url)  # override engine

    def fin():
        print("Disposing engine")
        engine.dispose()

    request.addfinalizer(fin)
    return engine


@pytest.fixture(scope='session')
def db(engine, sqlalchemy_connect_url):
    database_url = sqlalchemy_connect_url
    try:
        if not database_exists(database_url):
            create_database(database_url)
    except OperationalError:
        pytest.skip("No available db")
    connection = engine.connect()
    connection.execute('DROP SCHEMA IF EXISTS public CASCADE;')
    connection.execute('CREATE SCHEMA public;')
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
    m = mocker.patch('covreports.config._get_config_instance')
    mock_config = ConfigHelper()
    m.return_value = mock_config
    our_config = {
        'bitbucket': {'bot': {'username': 'codecov-io'}},
        'services': {
            'minio': {
                'access_key_id': 'codecov-default-key',
                'bucket': 'archive',
                'hash_key': '88f572f4726e4971827415efa8867978',
                'periodic_callback_ms': False,
                'secret_access_key': 'codecov-default-secret',
                'verify_ssl': False
            },
            'redis_url': 'redis://redis:@localhost:6379/'
        },
        'setup': {
            'codecov_url': 'https://codecov.io',
            'encryption_secret': 'zp^P9*i8aR3'
        }
    }
    mock_config.set_params(our_config)
    return mock_config


@pytest.fixture
def codecov_vcr(request):
    current_path = Path(request.node.fspath)
    current_path_name = current_path.name.replace('.py', '')
    cls_name = request.node.cls.__name__
    cassete_path = current_path.parent / 'cassetes' / current_path_name / cls_name
    current_name = request.node.name
    casset_file_path = str(cassete_path / f"{current_name}.yaml")
    with vcr.use_cassette(
            casset_file_path,
            record_mode='once',
            filter_headers=['authorization'],
            match_on=['method', 'scheme', 'host', 'port', 'path']) as cassete_maker:
        yield cassete_maker


@pytest.fixture
def mock_redis(mocker):
    m = mocker.patch('services.redis._get_redis_instance_from_url')
    redis_server = mocker.MagicMock()
    m.return_value = redis_server
    yield redis_server


@pytest.fixture
def mock_storage(mocker):
    m = mocker.patch('covreports.storage._get_appropriate_storage_service_given_storage')
    storage_server = MemoryStorageService({})
    m.return_value = storage_server
    yield storage_server


@pytest.fixture
def mock_repo_provider(mocker):
    f = Future()
    f.set_result({})
    m = mocker.patch('services.repository._get_repo_provider_service_instance')
    provider_instance = mocker.MagicMock(
        get_commit_diff=mocker.MagicMock(
            return_value=f
        )
    )
    m.return_value = provider_instance
    yield provider_instance
