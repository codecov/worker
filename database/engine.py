import dataclasses
import json
from json import JSONEncoder

from shared.config import get_config
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from .base import Base


def create_all(engine):
    Base.metadata.create_all(engine)


class DatabaseEncoder(JSONEncoder):
    def default(self, obj):
        if dataclasses.is_dataclass(obj):
            return dataclasses.astuple(obj)
        return super().default(self, obj)


def json_dumps(d):
    return json.dumps(d, cls=DatabaseEncoder)


default_database_url = "postgres://postgres:@postgres:5432/postgres"
main_engine = create_engine(
    get_config("services", "database_url", default=default_database_url),
    json_serializer=json_dumps,
)

session_factory = sessionmaker(bind=main_engine)
session = scoped_session(session_factory)

get_db_session = session
