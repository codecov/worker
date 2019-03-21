import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .base import Base


def create_all(engine):
    Base.metadata.create_all(engine)


def get_db_session():
    default_engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=default_engine)
    return Session()
