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
    """
    This model is defined here in order to describe the available columns and
    indexes on the table.  The table does not have a primary key and so you'll
    likely run into issues if you try to use the model in an ORM-style of loading
    and saving single records based on the primary key.  The primary key is defined
    below to appease SQLAlchemy only and is not intended to be used.

    See `services/timeseries.py` for an example of inserting/updating measurements.
    """

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


class Dataset(TimeseriesBaseModel):
    __tablename__ = "timeseries_dataset"

    id_ = Column("id", types.BigInteger, primary_key=True)
    name = Column(types.String(256), nullable=False)
    repository_id = Column(types.BigInteger, nullable=False)
    backfilled = Column(types.Boolean, nullable=False, default=False)

    __table_args__ = (
        Index(
            "timeseries_dataset_name_repo_unique",
            name,
            repository_id,
            unique=True,
        ),
    )
