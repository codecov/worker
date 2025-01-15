from sqlalchemy import Column, ForeignKey, types
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database.base import CodecovBaseModel, MixinBaseClass


class StaticAnalysisSuite(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "staticanalysis_staticanalysissuite"
    commit_id = Column(types.BigInteger, ForeignKey("commits.id"))
    # relationships
    commit = relationship("Commit")


class StaticAnalysisSingleFileSnapshot(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "staticanalysis_staticanalysissinglefilesnapshot"
    repository_id = Column(types.Integer, ForeignKey("repos.repoid"))
    file_hash = Column(UUID, nullable=False)
    content_location = Column(types.Text, nullable=False)
    state_id = Column(types.Integer, nullable=False)
    # relationships
    repository = relationship("Repository")


class StaticAnalysisSuiteFilepath(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "staticanalysis_staticanalysissuitefilepath"
    analysis_suite_id = Column(
        types.BigInteger, ForeignKey("staticanalysis_staticanalysissuite.id")
    )
    file_snapshot_id = Column(
        types.BigInteger,
        ForeignKey("staticanalysis_staticanalysissinglefilesnapshot.id"),
    )
    filepath = Column(types.Text, nullable=False)
    # relationships
    file_snapshot = relationship(StaticAnalysisSingleFileSnapshot)
    analysis_suite = relationship(StaticAnalysisSuite)
