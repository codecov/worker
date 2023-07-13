import json
import logging
from functools import cached_property, lru_cache

from shared.config import get_config
from shared.reports.types import ReportTotals, SessionTotalsArray
from shared.storage.exceptions import FileNotInStorageError
from sqlalchemy import Column, ForeignKey, Table, types
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import backref, relationship

from database.base import CodecovBaseModel, MixinBaseClass
from database.models.core import Commit, CompareCommit, Repository
from services.archive import ArchiveService

log = logging.getLogger(__name__)


class RepositoryFlag(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_repositoryflag"
    repository_id = Column(types.Integer, ForeignKey("repos.repoid"))
    repository = relationship(Repository, backref=backref("flags"))
    flag_name = Column(types.String(256), nullable=False)


class CommitReport(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_commitreport"
    commit_id = Column(types.BigInteger, ForeignKey("commits.id"))
    code = Column(types.String(100), nullable=True)
    commit: Commit = relationship(
        "Commit",
        foreign_keys=[commit_id],
        back_populates="reports_list",
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
    patch_results = relationship(
        "ReportResults",
        uselist=False,
        back_populates="report",
        cascade="all, delete",
        passive_deletes=True,
    )


uploadflagmembership = Table(
    "reports_uploadflagmembership",
    CodecovBaseModel.metadata,
    Column("upload_id", types.Integer, ForeignKey("reports_upload.id")),
    Column("flag_id", types.Integer, ForeignKey("reports_repositoryflag.id")),
)


class ReportResults(MixinBaseClass, CodecovBaseModel):
    __tablename__ = "reports_reportresults"
    state = Column(types.Text)
    completed_at = Column(types.DateTime(timezone=True), nullable=True)
    result = Column(postgresql.JSON)
    report_id = Column(types.Integer, ForeignKey("reports_commitreport.id"))
    report = relationship("CommitReport", foreign_keys=[report_id])


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
    flags = relationship(RepositoryFlag, secondary=uploadflagmembership)
    totals = relationship(
        "UploadLevelTotals",
        back_populates="upload",
        uselist=False,
        cascade="all, delete",
        passive_deletes=True,
    )
    upload_extras = Column(postgresql.JSON, nullable=False)
    upload_type = Column(types.String(100), nullable=False)
    state_id = Column(types.Integer)
    upload_type_id = Column(types.Integer)

    @cached_property
    def flag_names(self):
        return [f.flag_name for f in self.flags]


class UploadError(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_uploaderror"
    report_upload = relationship(Upload, backref="errors")
    upload_id = Column("upload_id", types.BigInteger, ForeignKey("reports_upload.id"))
    error_code = Column(types.String(100), nullable=False)
    error_params = Column(postgresql.JSON, default=dict)


class ReportDetails(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "reports_reportdetails"
    report_id = Column(types.Integer, ForeignKey("reports_commitreport.id"))
    report: CommitReport = relationship(
        "CommitReport", foreign_keys=[report_id], back_populates="details"
    )
    _files_array = Column("files_array", postgresql.ARRAY(postgresql.JSONB))
    _files_array_storage_path = Column(
        "files_array_storage_path", types.Text, nullable=True
    )

    def rehidrate_json(self, json_files_array):
        return [
            {
                **v,
                "file_totals": ReportTotals(*v["file_totals"]),
                "session_totals": SessionTotalsArray.build_from_encoded_data(
                    v["session_totals"]
                ),
                "diff_totals": ReportTotals(*v["diff_totals"])
                if v["diff_totals"]
                else None,
            }
            for v in json_files_array
        ]

    @lru_cache(maxsize=1)
    def _get_files_array(self):
        # Get files_array from the proper source
        if self._files_array is not None:
            return self._files_array
        repository = self.report.commit.repository
        archive_service = ArchiveService(repository=repository)
        try:
            file_str = archive_service.read_file(self._files_array_storage_path)
            return self.rehidrate_json(json.loads(file_str))
        except FileNotInStorageError:
            log.error(
                "files_array not in storage",
                extra=dict(
                    storage_path=self._files_array_storage_path,
                    report_details=self.id,
                    commit=self.report.commit,
                ),
            )
            # Return empty array to be consistent with current behavior
            # (instead of raising error)
            return []

    def _should_write_to_storage(self):
        # Safety check to see if the path to repository is valid
        # Because we had issues around this before
        if (
            self.report is None
            or self.report.commit is None
            or self.report.commit.repository is None
            or self.report.commit.repository.slug is None
        ):
            return False
        report_builder_repo_ids = get_config(
            "setup", "save_report_data_in_storage", "repo_ids", default=[]
        )
        master_write_switch = get_config(
            "setup",
            "save_report_data_in_storage",
            "report_details_files_array",
            default=False,
        )
        only_codecov = get_config(
            "setup",
            "save_report_data_in_storage",
            "only_codecov",
            default=True,
        )
        is_codecov_repo = self.report.commit.repository.slug.startswith("codecov/")
        is_repo_allowed = (
            self.report.commit.repository.repoid in report_builder_repo_ids
        )
        return master_write_switch and (
            not only_codecov or is_codecov_repo or is_repo_allowed
        )

    def _set_files_array(self, files_array: dict):
        # Invalidate the cache for the getter method
        self._get_files_array.cache_clear()
        # Set the new value
        if self._should_write_to_storage():
            repository = self.report.commit.repository
            archive_service = ArchiveService(repository=repository)
            path = archive_service.write_json_data_to_storage(
                commit_id=self.report.commit.commitid,
                model="ReportDetails",
                field="files_array",
                external_id=self.external_id,
                data=files_array,
            )
            self._files_array_storage_path = path
            self._files_array = None
        else:
            self._files_array = files_array

    files_array = property(fget=_get_files_array, fset=_set_files_array)


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


class CompareFlag(MixinBaseClass, CodecovBaseModel):
    __tablename__ = "compare_flagcomparison"

    commit_comparison_id = Column(
        types.BigInteger, ForeignKey("compare_commitcomparison.id")
    )
    repositoryflag_id = Column(types.Integer, ForeignKey("reports_repositoryflag.id"))
    head_totals = Column(postgresql.JSON)
    base_totals = Column(postgresql.JSON)
    patch_totals = Column(postgresql.JSON)

    commit_comparison = relationship(CompareCommit, foreign_keys=[commit_comparison_id])
    repositoryflag = relationship(RepositoryFlag, foreign_keys=[repositoryflag_id])


class CompareComponent(MixinBaseClass, CodecovBaseModel):
    __tablename__ = "compare_componentcomparison"

    commit_comparison_id = Column(
        types.BigInteger, ForeignKey("compare_commitcomparison.id")
    )
    component_id = Column(types.String(100), nullable=False)
    head_totals = Column(postgresql.JSON)
    base_totals = Column(postgresql.JSON)
    patch_totals = Column(postgresql.JSON)

    commit_comparison = relationship(CompareCommit, foreign_keys=[commit_comparison_id])
