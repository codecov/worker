from pathlib import Path

import pytest
import vcr

from database.base import Base
from sqlalchemy_utils import create_database, database_exists
from helpers.config import config


@pytest.fixture(scope='session', autouse=True)
def db(engine, sqlalchemy_connect_url):
    database_url = sqlalchemy_connect_url
    if not database_exists(database_url):
        create_database(database_url)
    connection = engine.connect()
    connection.execute('DROP SCHEMA IF EXISTS public CASCADE;')
    connection.execute('CREATE SCHEMA public;')
    Base.metadata.create_all(engine)


@pytest.fixture(scope='session', autouse=True)
def test_configuration():
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
    config.set_params(our_config)
    return our_config


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
    m = mocker.patch('services.archive.StorageService')
    redis_server = mocker.MagicMock()
    m.return_value = redis_server
    yield redis_server
