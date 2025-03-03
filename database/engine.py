import dataclasses
import json
from decimal import Decimal

from shared.config import get_config
from shared.timeseries.helpers import is_timeseries_enabled
from shared.utils.ReportEncoder import ReportEncoder
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

import database.events  # noqa: F401
from database.models.timeseries import TimeseriesBaseModel

from .base import Base


def create_all(engine):
    Base.metadata.create_all(engine)


class DatabaseEncoder(ReportEncoder):
    def default(self, obj):
        if dataclasses.is_dataclass(obj):
            return dataclasses.astuple(obj)
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def json_dumps(d):
    return json.dumps(d, cls=DatabaseEncoder)


class SessionFactory:
    def __init__(self, database_url, timeseries_database_url=None):
        self.database_url = database_url
        self.timeseries_database_url = timeseries_database_url
        self.main_engine = None
        self.timeseries_engine = None

    def create_session(self):
        self.main_engine = create_engine(
            self.database_url,
            json_serializer=json_dumps,
        )

        if is_timeseries_enabled():
            self.timeseries_engine = create_engine(
                self.timeseries_database_url,
                json_serializer=json_dumps,
            )

            main_engine = self.main_engine
            timeseries_engine = self.timeseries_engine

            class RoutingSession(Session):
                def get_bind(self, mapper=None, clause=None, **kwargs):
                    if mapper is not None and issubclass(
                        mapper.class_, TimeseriesBaseModel
                    ):
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
            session_factory = sessionmaker(bind=self.main_engine)

        return scoped_session(session_factory)


session_factory = SessionFactory(
    database_url=get_config(
        "services",
        "database_url",
        default="postgresql://postgres:@postgres:5432/postgres",
    ),
    timeseries_database_url=get_config(
        "services",
        "timeseries_database_url",
        default="postgresql://postgres:@timescale:5432/postgres",
    ),
)

session = session_factory.create_session()

get_db_session = session
