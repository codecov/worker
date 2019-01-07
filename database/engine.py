import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

default_engine = create_engine(os.getenv('DATABASE_URL'))


def create_all(engine):
    Base.metadata.create_all(engine)


def get_db_session():
    Session = sessionmaker(bind=default_engine)
    return Session()
