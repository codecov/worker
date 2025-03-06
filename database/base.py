import uuid

from sqlalchemy import Column, types
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session

from helpers.clock import get_utc_now

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
    created_at = Column(types.DateTime(timezone=True), default=get_utc_now)
    updated_at = Column(
        types.DateTime(timezone=True), onupdate=get_utc_now, default=get_utc_now
    )

    @property
    def id(self):
        return self.id_


class MixinBaseClassNoExternalID(object):
    id_ = Column("id", types.BigInteger, primary_key=True)
    created_at = Column(types.DateTime(timezone=True), default=get_utc_now)
    updated_at = Column(
        types.DateTime(timezone=True), onupdate=get_utc_now, default=get_utc_now
    )

    @property
    def id(self):
        return self.id_
