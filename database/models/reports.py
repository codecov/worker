import uuid
import datetime
import logging
from functools import cached_property

from sqlalchemy import Column, types, ForeignKey, Table
from sqlalchemy.orm import relationship, backref
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects import postgresql

from database.base import CodecovBaseModel
from database.models.core import Repository


log = logging.getLogger(__name__)


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


class RepositoryFlag(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_repositoryflag"
    repository_id = Column(types.Integer, ForeignKey("repos.repoid"))
    repository = relationship(Repository, backref=backref("flags"))
    flag_name = Column(types.String(256), nullable=False)


class CommitReport(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_commitreport"
    commit_id = Column(types.BigInteger, ForeignKey("commits.id"))
    commit = relationship(
        "Commit",
        foreign_keys=[commit_id],
        back_populates="report",
        cascade="all, delete",
    )
    details = relationship(
        "ReportDetails",
        back_populates="report",
        uselist=False,
        cascade="all, delete",
        passive_deletes=True,
    )
    totals = relationship(
        "ReportLevelTotals",
        back_populates="report",
        uselist=False,
        cascade="all, delete",
        passive_deletes=True,
    )
    uploads = relationship(
        "Upload", back_populates="report", cascade="all, delete", passive_deletes=True
    )


association_table = Table(
    "reports_uploadflagmembership",
    CodecovBaseModel.metadata,
    Column("upload_id", types.Integer, ForeignKey("reports_upload.id")),
    Column("flag_id", types.Integer, ForeignKey("reports_repositoryflag.id")),
)


class Upload(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_upload"
    build_code = Column(types.Text)
    build_url = Column(types.Text)
    env = Column(postgresql.JSON)
    job_code = Column(types.Text)
    name = Column(types.String(100))
    provider = Column(types.String(50))
    report_id = Column(types.BigInteger, ForeignKey("reports_commitreport.id"))
    report = relationship(
        "CommitReport", foreign_keys=[report_id], back_populates="uploads"
    )
    state = Column(types.String(100), nullable=False)
    storage_path = Column(types.Text, nullable=False)
    order_number = Column(types.Integer)
    flags = relationship(RepositoryFlag, secondary=association_table)
    totals = relationship(
        "UploadLevelTotals",
        back_populates="upload",
        uselist=False,
        cascade="all, delete",
        passive_deletes=True,
    )
    upload_extras = Column(postgresql.JSON, nullable=False)
    upload_type = Column(types.String(100), nullable=False)

    @cached_property
    def flag_names(self):
        return [f.flag_name for f in self.flags]


class UploadError(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_uploaderror"
    report_session = relationship(Upload, backref="errors")
    upload_id = Column("upload_id", types.BigInteger, ForeignKey("reports_upload.id"))
    error_code = Column(types.String(100), nullable=False)
    error_params = Column(postgresql.JSON, default=dict)


class ReportDetails(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_reportdetails"
    report_id = Column(types.Integer, ForeignKey("reports_commitreport.id"))
    report = relationship(
        "CommitReport", foreign_keys=[report_id], back_populates="details"
    )
    files_array = Column(postgresql.ARRAY(postgresql.JSONB))


class AbstractTotals(MixinBaseClass):
    branches = Column(types.Integer)
    coverage = Column(types.Numeric(precision=7, scale=2))
    hits = Column(types.Integer)
    lines = Column(types.Integer)
    methods = Column(types.Integer)
    misses = Column(types.Integer)
    partials = Column(types.Integer)
    files = Column(types.Integer)

    def update_from_totals(self, totals):
        self.branches = totals.branches
        # Temporary until the table starts accepting NULLs
        self.coverage = totals.coverage if totals.coverage is not None else 0
        self.hits = totals.hits
        self.lines = totals.lines
        self.methods = totals.methods
        self.misses = totals.misses
        self.partials = totals.partials
        self.files = totals.files

    class Meta:
        abstract = True


class ReportLevelTotals(CodecovBaseModel, AbstractTotals):
    __tablename__ = "reports_reportleveltotals"
    report_id = Column(types.Integer, ForeignKey("reports_commitreport.id"))
    report = relationship("CommitReport", foreign_keys=[report_id])


class UploadLevelTotals(CodecovBaseModel, AbstractTotals):
    __tablename__ = "reports_uploadleveltotals"
    upload_id = Column("upload_id", types.Integer, ForeignKey("reports_upload.id"))
    upload = relationship("Upload", foreign_keys=[upload_id])
