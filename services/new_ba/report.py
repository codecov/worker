import json
import os
import sqlite3
import tempfile
from typing import Any, Dict, Iterator, Optional, Self

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql import func

from services.new_ba import models
from services.new_ba.parser import Parser


class ModuleReport:
    """
    Report wrapper around a single module (many of which can exist in a single Asset via Chunks)
    """

    def __init__(self, db_path: str, module: models.Module):
        self.db_path = db_path
        self.module = module

    @property
    def name(self):
        return self.module.name

    @property
    def size(self):
        return self.module.size


class AssetReport:
    """
    Report wrapper around a single asset (many of which can exist in a single bundle).
    """

    def __init__(self, db_path: str, asset: models.Asset):
        self.db_path = db_path
        self.asset = asset

    @property
    def name(self):
        return self.asset.normalized_name

    @property
    def hashed_name(self):
        return self.asset.name

    @property
    def size(self):
        return self.asset.size

    @property
    def uuid(self):
        return self.asset.uuid

    @property
    def asset_type(self):
        return self.asset.asset_type

    def modules(self):
        with models.get_db_session(self.db_path) as session:
            modules = (
                session.query(models.Module)
                .join(models.Module.chunks)
                .join(models.Chunk.assets)
                .filter(models.Asset.id == self.asset.id)
                .all()
            )
            return [ModuleReport(self.db_path, module) for module in modules]


class BundleReport:
    """
    Report wrapper around a single bundle (many of which can exist in a single analysis report).
    """

    def __init__(self, db_path: str, bundle: models.Bundle):
        self.db_path = db_path
        self.bundle = bundle

    @property
    def name(self):
        return self.bundle.name

    def asset_reports(self) -> Iterator[AssetReport]:
        with models.get_db_session(self.db_path) as session:
            assets = (
                session.query(models.Asset)
                .join(models.Asset.session)
                .join(models.Session.bundle)
                .filter(models.Bundle.id == self.bundle.id)
                .all()
            )
            return (AssetReport(self.db_path, asset) for asset in assets)

    def total_size(self) -> int:
        with models.get_db_session(self.db_path) as session:
            return (
                session.query(func.sum(models.Asset.size).label("asset_size"))
                .join(models.Asset.session)
                .join(models.Session.bundle)
                .filter(models.Session.bundle_id == self.bundle.id)
                .scalar()
            ) or 0

    def info(self) -> dict:
        with models.get_db_session(self.db_path) as session:
            result = (
                session.query(models.Session)
                .filter(models.Session.bundle_id == self.bundle.id)
                .first()
            )
            return json.loads(result.info)


class BundleAnalysisReport:
    """
    Report wrapper around multiple bundles for a single commit report.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        if self.db_path is None:
            _, self.db_path = tempfile.mkstemp(prefix="bundle_analysis_")
        self.db_session = models.get_db_session(self.db_path, auto_close=False)
        self._setup()

    def _setup(self):
        """
        Creates the schema for a new bundle report database.
        """
        try:
            schema_version = (
                self.db_session.query(models.Metadata)
                .filter_by(key=models.MetadataKey.SCHEMA_VERSION.value)
                .first()
            )
            self._migrate(schema_version.value)
        except OperationalError:
            # schema does not exist
            con = sqlite3.connect(self.db_path)
            con.executescript(models.SCHEMA)
            schema_version = models.Metadata(
                key=models.MetadataKey.SCHEMA_VERSION.value,
                value=models.SCHEMA_VERSION,
            )
            self.db_session.add(schema_version)
            self.db_session.commit()

    def _migrate(self, schema_version: int):
        """
        Migrate the database from `schema_version` to `models.SCHEMA_VERSION`
        such that the resulting schema is identical to `models.SCHEMA`
        """
        # we don't have any migrations yet
        assert schema_version == models.SCHEMA_VERSION

    def cleanup(self):
        self.db_session.close()
        os.unlink(self.db_path)

    def ingest(self, path: str) -> int:
        """
        Ingest the bundle stats JSON at the given file path.
        Returns session ID of ingested data.
        """
        parser = Parser(self.db_session)
        session_id = parser.parse(path)
        self.db_session.commit()
        return session_id

    def associate_previous_assets(self, prev_bundle_analysis_report: Self) -> None:
        """
        Only associate past asset if it is Javascript or Typescript types
        and belonging to the same bundle name
        Associated if one of the following is true
        Rule 1. Previous and current asset have the same hashed name
        Rule 2. Previous and current asset shared the same set of module names
        """
        for curr_bundle_report in self.bundle_reports():
            for prev_bundle_report in prev_bundle_analysis_report.bundle_reports():
                if curr_bundle_report.name == prev_bundle_report.name:
                    associated_assets_found = []

                    # Rule 1 check
                    prev_asset_hashed_names = {
                        a.hashed_name: a.uuid for a in prev_bundle_report.asset_reports()
                    }
                    for curr_asset in curr_bundle_report.asset_reports():
                        if curr_asset.asset_type in [models.AssetType.JAVASCRIPT, models.AssetType.TYPESCRIPT]:
                            if curr_asset.hashed_name in prev_asset_hashed_names:
                                associated_assets_found.append([
                                    prev_asset_hashed_names[curr_asset.hashed_name],
                                    curr_asset.uuid
                                ])

                    # Rule 2 check
                    prev_module_asset_mapping = {}
                    for prev_asset in prev_bundle_report.asset_reports():
                        if prev_asset.asset_type in [models.AssetType.JAVASCRIPT, models.AssetType.TYPESCRIPT]:
                            prev_modules = tuple(sorted(frozenset([m.name for m in prev_asset.modules()])))
                            # NOTE: Assume two assets CANNOT have the exact same of modules
                            # though in reality there can be rare cases of this
                            # but we will deal with that later if it becomes a prevalent problem
                            prev_module_asset_mapping[prev_modules] = prev_asset.uuid

                    for curr_asset in curr_bundle_report.asset_reports():
                        if curr_asset.asset_type in [models.AssetType.JAVASCRIPT, models.AssetType.TYPESCRIPT]:
                            curr_modules = tuple(sorted(frozenset([m.name for m in curr_asset.modules()])))
                            if curr_modules in prev_module_asset_mapping:
                                associated_assets_found.append([
                                    prev_module_asset_mapping[curr_modules],
                                    curr_asset.uuid
                                ])

                    # Update the Assets table for the bundle
                    # TODO: Use SQLalchemy ORM to update instead of raw SQL
                    for pair in associated_assets_found:
                        prev_uuid, curr_uuid = pair
                        stmt = f"UPDATE assets SET uuid='{prev_uuid}' WHERE uuid='{curr_uuid}'"
                        self.db_session.execute(text(stmt))
                    self.db_session.commit()

    def metadata(self) -> Dict[models.MetadataKey, Any]:
        with models.get_db_session(self.db_path) as session:
            metadata = session.query(models.Metadata).all()
            return {models.MetadataKey(item.key): item.value for item in metadata}

    def bundle_reports(self) -> Iterator[BundleReport]:
        with models.get_db_session(self.db_path) as session:
            bundles = session.query(models.Bundle).all()
            return (BundleReport(self.db_path, bundle) for bundle in bundles)

    def bundle_report(self, bundle_name: str) -> Optional[BundleReport]:
        with models.get_db_session(self.db_path) as session:
            bundle = session.query(models.Bundle).filter_by(name=bundle_name).first()
            if bundle is None:
                return None
            return BundleReport(self.db_path, bundle)

    def session_count(self) -> int:
        with models.get_db_session(self.db_path) as session:
            return session.query(models.Session).count()
