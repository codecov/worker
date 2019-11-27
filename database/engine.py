from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from .base import Base
from covreports.config import get_config


def create_all(engine):
    Base.metadata.create_all(engine)


default_database_url = 'postgres://postgres:@postgres:5432/postgres'
main_engine = create_engine(get_config('services', 'database_url', default=default_database_url))

session_factory = sessionmaker(bind=main_engine)
session = scoped_session(session_factory)

get_db_session = session
