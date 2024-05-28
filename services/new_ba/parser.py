import json
import logging
import os
import re
import uuid
from typing import Optional, Tuple

import ijson
from sqlalchemy.orm import Session as DbSession

from services.new_ba.models import (
    SCHEMA,
    Asset,
    AssetType,
    Bundle,
    Chunk,
    Module,
    Session,
    assets_chunks,
    chunks_modules,
)
from services.new_ba.utils import get_extension

log = logging.getLogger(__name__)


class Parser:
    """
    This does a streaming JSON parse of the stats JSON file referenced by `path`.
    It's more complicated that just doing a `json.loads` but should keep our memory
    usage constrained.
    """

    def __init__(self, db_session: DbSession):
        self.db_session = db_session

    def reset(self):
        """
        Resets temporary parser state in order to parse a new file path.
        """
        # chunk unique id -> asset name list
        self.chunk_asset_names_index = {}

        # module name -> chunk external id list
        self.module_chunk_unique_external_ids_index = {}

        # misc. top-level info from the stats data (i.e. bundler version, bundle time, etc.)
        self.info = {}

        # temporary parser state
        self.session = None
        self.asset = None
        self.chunk = None
        self.chunk_asset_names = []
        self.module = None
        self.module_chunk_unique_external_ids = []

        self.asset_list = []
        self.chunk_list = []
        self.module_list = []

    def parse(self, path: str) -> int:
        try:
            self.reset()

            # Retrieve the info section first before parsing all the other things
            # this way when an error is raised we know which bundle plugin caused it
            with open(path, "rb") as f:
                for event in ijson.parse(f):
                    self._parse_info(event)

            self.session = Session(info={})
            self.db_session.add(self.session)
            self.db_session.flush()

            with open(path, "rb") as f:
                for event in ijson.parse(f):
                    self._parse_event(event)

                if self.asset_list:
                    insert_asset = Asset.__table__.insert().values(self.asset_list)
                    self.db_session.execute(insert_asset)

                if self.chunk_list:
                    insert_chunks = Chunk.__table__.insert().values(self.chunk_list)
                    self.db_session.execute(insert_chunks)

                if self.module_list:
                    insert_modules = Module.__table__.insert().values(self.module_list)
                    self.db_session.execute(insert_modules)

                self.db_session.flush()

                # Delete old session/asset/chunk/module with the same bundle name if applicable
                old_session = (
                    self.db_session.query(Session)
                    .filter(
                        Session.bundle == self.session.bundle,
                        Session.id != self.session.id,
                    )
                    .one_or_none()
                )
                if old_session:
                    for model in [Asset, Chunk, Module]:
                        to_be_deleted = self.db_session.query(model).filter(
                            model.session == old_session
                        )
                        for item in to_be_deleted:
                            self.db_session.delete(item)
                            self.db_session.flush()
                    self.db_session.delete(old_session)
                    self.db_session.flush()

                # save top level bundle stats info
                self.session.info = json.dumps(self.info)

                # this happens last so that we could potentially handle any ordering
                # of top-level keys inside the JSON (i.e. we couldn't associate a chunk
                # to an asset above if we parse the chunk before the asset)
                self._create_associations()

                assert self.session.bundle is not None
                return self.session.id
        except Exception as e:
            # Inject the plugin name to the Exception object so we have visibilitity on which plugin
            # is causing the trouble.
            e.bundle_analysis_plugin_name = self.info.get("plugin_name", "unknown")
            raise e

    def _asset_type(self, name: str) -> AssetType:
        extension = get_extension(name)

        if extension in ["js"]:
            return AssetType.JAVASCRIPT
        if extension in ["ts"]:
            return AssetType.STYLESHEET
        if extension in ["woff", "woff2", "ttf", "otf", "eot"]:
            return AssetType.FONT
        if extension in ["jpg", "jpeg", "png", "gif", "svg", "webp", "apng", "avif"]:
            return AssetType.IMAGE

        return AssetType.UNKNOWN

    def _parse_info(self, event: Tuple[str, str, str]):
        prefix, _, value = event

        # session info
        if prefix == "version":
            self.info["version"] = value
        elif prefix == "bundler.name":
            self.info["bundler_name"] = value
        elif prefix == "bundler.version":
            self.info["bundler_version"] = value
        elif prefix == "builtAt":
            self.info["built_at"] = value
        elif prefix == "plugin.name":
            self.info["plugin_name"] = value
        elif prefix == "plugin.version":
            self.info["plugin_version"] = value
        elif prefix == "duration":
            self.info["duration"] = value

    def _parse_event(self, event: Tuple[str, str, str]):
        prefix, _, value = event
        prefix_path = prefix.split(".")

        # asset / chunks / modules
        if prefix_path[0] == "assets":
            self._parse_assets_event(*event)
        elif prefix_path[0] == "chunks":
            self._parse_chunks_event(*event)
        elif prefix_path[0] == "modules":
            self._parse_modules_event(*event)

        # bundle name
        elif prefix == "bundleName":
            if not re.fullmatch(r"^[\w\d_:/@\.{}\[\]$-]+$", value):
                log.info(f'bundle name does not match regex: "{value}"')
                raise Exception("invalid bundle name")
            bundle = self.db_session.query(Bundle).filter_by(name=value).first()
            if bundle is None:
                bundle = Bundle(name=value)
                self.db_session.add(bundle)
            self.session.bundle = bundle

    def _parse_assets_event(self, prefix: str, event: str, value: str):
        if (prefix, event) == ("assets.item", "start_map"):
            # new asset
            assert self.asset is None
            self.asset = Asset(session_id=self.session.id)
        elif prefix == "assets.item.name":
            self.asset.name = value
        elif prefix == "assets.item.normalized":
            self.asset.normalized_name = value
        elif prefix == "assets.item.size":
            self.asset.size = int(value)
        elif (prefix, event) == ("assets.item", "end_map"):
            self.asset_list.append(
                dict(
                    session_id=self.asset.session_id,
                    name=self.asset.name,
                    normalized_name=self.asset.normalized_name,
                    size=self.asset.size,
                    uuid=str(uuid.uuid4()),
                    asset_type=self._asset_type(self.asset.name),
                )
            )

            # reset parser state
            self.asset = None

    def _parse_chunks_event(self, prefix: str, event: str, value: str):
        if (prefix, event) == ("chunks.item", "start_map"):
            # new chunk
            assert self.chunk is None
            self.chunk = Chunk(session_id=self.session.id)
        elif prefix == "chunks.item.id":
            self.chunk.external_id = value
        elif prefix == "chunks.item.uniqueId":
            self.chunk.unique_external_id = value
        elif prefix == "chunks.item.initial":
            self.chunk.initial = value
        elif prefix == "chunks.item.entry":
            self.chunk.entry = value
        elif prefix == "chunks.item.files.item":
            self.chunk_asset_names.append(value)
        elif (prefix, event) == ("chunks.item", "end_map"):
            self.chunk_list.append(
                dict(
                    session_id=self.chunk.session_id,
                    external_id=self.chunk.external_id,
                    unique_external_id=self.chunk.unique_external_id,
                    initial=self.chunk.initial,
                    entry=self.chunk.entry,
                )
            )

            self.chunk_asset_names_index[self.chunk.unique_external_id] = (
                self.chunk_asset_names
            )
            # reset parser state
            self.chunk = None
            self.chunk_asset_names = []

    def _parse_modules_event(self, prefix: str, event: str, value: str):
        if (prefix, event) == ("modules.item", "start_map"):
            # new module
            assert self.module is None
            self.module = Module(session_id=self.session.id)
        elif prefix == "modules.item.name":
            self.module.name = value
        elif prefix == "modules.item.size":
            self.module.size = int(value)
        elif prefix == "modules.item.chunkUniqueIds.item":
            self.module_chunk_unique_external_ids.append(value)
        elif (prefix, event) == ("modules.item", "end_map"):
            self.module_list.append(
                dict(
                    session_id=self.module.session_id,
                    name=self.module.name,
                    size=self.module.size,
                )
            )

            self.module_chunk_unique_external_ids_index[self.module.name] = (
                self.module_chunk_unique_external_ids
            )
            # reset parser state
            self.module = None
            self.module_chunk_unique_external_ids = []

    def _create_associations(self):
        # associate chunks to assets
        inserts = []
        assets: list[Asset] = (
            self.db_session.query(Asset)
            .filter(
                Asset.session_id == self.session.id,
            )
            .all()
        )

        asset_name_to_id = {asset.name: asset.id for asset in assets}

        chunks: list[Chunk] = (
            self.db_session.query(Chunk)
            .filter(
                Chunk.session_id == self.session.id,
            )
            .all()
        )

        chunk_unique_id_to_id = {chunk.unique_external_id: chunk.id for chunk in chunks}

        modules = (
            self.db_session.query(Module)
            .filter(
                Module.session_id == self.session.id,
            )
            .all()
        )

        for chunk in chunks:
            chunk_id = chunk.id
            asset_names = self.chunk_asset_names_index[chunk.unique_external_id]
            inserts.extend(
                [
                    dict(asset_id=asset_name_to_id[asset_name], chunk_id=chunk_id)
                    for asset_name in asset_names
                ]
            )
        if inserts:
            self.db_session.execute(assets_chunks.insert(), inserts)

        # associate modules to chunks
        # FIXME: this isn't quite right - need to sort out how non-JS assets reference chunks
        inserts = []

        modules: list[Module] = self.db_session.query(Module).filter(
            Module.session_id == self.session.id,
        )
        for module in modules:
            module_id = module.id
            chunk_unique_external_ids = self.module_chunk_unique_external_ids_index[
                module.name
            ]

            inserts.extend(
                [
                    dict(
                        chunk_id=chunk_unique_id_to_id[unique_external_id],
                        module_id=module_id,
                    )
                    for unique_external_id in chunk_unique_external_ids
                ]
            )
        if inserts:
            self.db_session.execute(chunks_modules.insert(), inserts)
