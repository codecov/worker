from enum import Enum

from sqlalchemy import Column, types
from sqlalchemy.schema import Index

from database.base import CodecovBaseModel


class TimeseriesBaseModel(CodecovBaseModel):
    __abstract__ = True


class MeasurementName(Enum):
    coverage = "coverage"
    flag_coverage = "flag_coverage"
    component_coverage = "component_coverage"
    # For tracking the entire size of a bundle report by its name
    bundle_analysis_report_size = "bundle_analysis_report_size"
    # For tracking the size of a category of assets of a bundle report by its name
    bundle_analysis_javascript_size = "bundle_analysis_javascript_size"
    bundle_analysis_stylesheet_size = "bundle_analysis_stylesheet_size"
    bundle_analysis_font_size = "bundle_analysis_font_size"
    bundle_analysis_image_size = "bundle_analysis_image_size"
    # For tracking individual asset size via its UUID
    bundle_analysis_asset_size = "bundle_analysis_asset_size"


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
    measurable_id = Column(types.String(256))
    branch = Column(types.String(256))
    commit_sha = Column(types.String(256), nullable=False)
    name = Column(types.String(256), nullable=False)
    value = Column(types.Float, nullable=False)

    __table_args__ = (
        Index(
            "timeseries_measurement_measurable_unique",
            timestamp,
            owner_id,
            repo_id,
            measurable_id,
            commit_sha,
            name,
            unique=True,
        ),
    )

    __mapper_args__ = {
        "primary_key": [
            timestamp,
            owner_id,
            repo_id,
            measurable_id,
            commit_sha,
            name,
        ]
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
