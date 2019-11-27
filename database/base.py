from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

Base = declarative_base()


class CodecovBaseModel(Base):

    __abstract__ = True

    def get_db_session(self):
        return Session.object_session(self)
