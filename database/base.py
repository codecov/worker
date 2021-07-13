import datetime
import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
from sqlalchemy import Column, types

Base = declarative_base()


class CodecovBaseModel(Base):

    __abstract__ = True

    def get_db_session(self):
        return Session.object_session(self)


class MixinBaseClass(object):
    id_ = Column("id", types.BigInteger, primary_key=True)
    external_id = Column(
        UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
    )
    created_at = Column(types.DateTime, default=datetime.datetime.now)
    updated_at = Column(
        types.DateTime, onupdate=datetime.datetime.now, default=datetime.datetime.now
    )

    @property
    def id(self):
        return self.id_
