import uuid

from sqlalchemy import Column, ForeignKey, types
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database.base import CodecovBaseModel
from helpers.clock import get_utc_now


class MixinBaseClass(object):
    id = Column("id", types.BigInteger, primary_key=True)
    external_id = Column(
        UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False
    )
    created_at = Column(types.DateTime(timezone=True), default=get_utc_now)
    updated_at = Column(
        types.DateTime(timezone=True), onupdate=get_utc_now, default=get_utc_now
    )


class ProfilingCommit(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "profiling_profilingcommit"
    last_joined_uploads_at = Column(types.DateTime(timezone=True), nullable=True)
    joined_location = Column(types.Text)
    last_summarized_at = Column(types.DateTime(timezone=True), nullable=True)
    summarized_location = Column(types.Text)
    version_identifier = Column(types.Text, nullable=False)
    repoid = Column(types.Integer, ForeignKey("repos.repoid"))
    repository = relationship("Repository")


class ProfilingUpload(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "profiling_profilingupload"
    raw_upload_location = Column(types.Text, nullable=False)
    profiling_commit_id = Column(
        types.BigInteger, ForeignKey("profiling_profilingcommit.id")
    )
    profiling_commit = relationship(ProfilingCommit)
    normalized_at = Column(types.DateTime(timezone=True), nullable=True)
    normalized_location = Column(types.Text)
