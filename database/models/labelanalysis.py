from sqlalchemy import Column, ForeignKey, types
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship

from database.base import CodecovBaseModel, MixinBaseClass


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
