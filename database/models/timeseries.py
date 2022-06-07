from enum import Enum

from sqlalchemy import Column, types
from sqlalchemy.schema import Index

from database.base import CodecovBaseModel


class TimeseriesBaseModel(CodecovBaseModel):

    __abstract__ = True


class MeasurementName(Enum):
    coverage = "coverage"
    flag_coverage = "flag_coverage"


class Measurement(TimeseriesBaseModel):

    __tablename__ = "timeseries_measurement"

    timestamp = Column(types.DateTime(timezone=True), nullable=False)
    owner_id = Column(types.BigInteger, nullable=False)
    repo_id = Column(types.BigInteger, nullable=False)
    flag_id = Column(types.BigInteger)
    branch = Column(types.String(256))
    commit_sha = Column(types.String(256), nullable=False)
    name = Column(types.String(256), nullable=False)
    value = Column(types.Float, nullable=False)

    __table_args__ = (
        Index(
            "timeseries_measurement_noflag_unique",
            timestamp,
            owner_id,
            repo_id,
            commit_sha,
            name,
            unique=True,
            postgresql_where=flag_id.is_(None),
        ),
        Index(
            "timeseries_measurement_flag_unique",
            timestamp,
            owner_id,
            repo_id,
            flag_id,
            commit_sha,
            name,
            unique=True,
            postgresql_where=flag_id.isnot(None),
        ),
    )

    __mapper_args__ = {
        "primary_key": [timestamp, owner_id, repo_id, flag_id, commit_sha, name]
    }
