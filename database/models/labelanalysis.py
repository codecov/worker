from enum import Enum

from sqlalchemy import Column, ForeignKey, types
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship

from database.base import CodecovBaseModel, MixinBaseClass


class LabelAnalysisProcessingErrorCode(Enum):
    NOT_FOUND = "not found"
    FAILED = "failed"
    MISSING_DATA = "missing data"


class LabelAnalysisRequest(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "labelanalysis_labelanalysisrequest"
    base_commit_id = Column(types.BigInteger, ForeignKey("commits.id"), nullable=False)
    head_commit_id = Column(types.BigInteger, ForeignKey("commits.id"), nullable=False)
    requested_labels = Column(postgresql.ARRAY(types.Text), nullable=True)
    state_id = Column(types.Integer, nullable=False)
    result = Column(postgresql.JSON, nullable=True)
    # relationships
    base_commit = relationship("Commit", foreign_keys=[base_commit_id])
    head_commit = relationship("Commit", foreign_keys=[head_commit_id])


class LabelAnalysisProcessingError(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "labelanalysis_labelanalysisprocessingerror"
    label_analysis_request = relationship(LabelAnalysisRequest, backref="errors")
    label_analysis_request_id = Column(
        "label_analysis_request_id",
        types.BigInteger,
        ForeignKey("labelanalysis_labelanalysisrequest.id"),
    )
    error_code = Column(types.String(100), nullable=False)
    error_params = Column(postgresql.JSON, nullable=True)

    def to_representation(self):
        return dict(error_code=self.error_code, error_params=self.error_params)
