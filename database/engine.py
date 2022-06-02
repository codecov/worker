import dataclasses
import json
from json import JSONEncoder

from shared.config import get_config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from database.models.timeseries import TimeseriesBaseModel

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

timeseries_enabled = get_config("setup", "timeseries", "enabled", default=False)
if timeseries_enabled:
    default_timeseries_database_url = "postgres://postgres:@timescale:5432/postgres"
    timeseries_engine = create_engine(
        get_config(
            "services",
            "timeseries_database_url",
            default=default_timeseries_database_url,
        ),
        json_serializer=json_dumps,
    )

    class RoutingSession(Session):
        def get_bind(self, mapper=None, clause=None):
            if mapper is not None and isinstance(mapper.class_, TimeseriesBaseModel):
                return timeseries_engine
            if (
                clause is not None
                and hasattr(clause, "table")
                and clause.table.name.startswith("timeseries_")
            ):
                return timeseries_engine
            return main_engine

    session_factory = sessionmaker(class_=RoutingSession)
else:
    session_factory = sessionmaker(bind=main_engine)

session = scoped_session(session_factory)

get_db_session = session
