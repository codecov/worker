import logging
from enum import Enum
from typing import List, Optional

import sqlalchemy
from sqlalchemy import Column, Enum as SQLAlchemyEnum, ForeignKey, Table, create_engine, types
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import backref, relationship, sessionmaker

log = logging.getLogger(__name__)


SCHEMA = """
create table bundles (
    id integer primary key,
    name text
);

--- only allow 1 null name (the default bundle)
create unique index bundles_name_index on bundles (ifnull(name, 'codecov-default-bundle-name'));

create table sessions (
    id integer primary key,
    info text not null,
    bundle_id integer, --- this is nullable just temporarily while parsing
    foreign key (bundle_id) references bundles (id)
);

create index sessions_bundle_id_index on sessions (bundle_id);

create table metadata (
    key text primary key,
    value text not null
);

create table assets (
    id integer primary key,
    session_id integer not null,
    name text not null,
    normalized_name text not null,
    size integer not null,
    uuid text not null,
    asset_type text not null,
    foreign key (session_id) references sessions (id)
);

create index assets_session_id_index on assets (session_id);
create index assets_name_index on assets (name);

create table chunks (
    id integer primary key,
    session_id integer not null,
    external_id text not null,
    unique_external_id text not null,
    entry boolean not null,
    initial boolean not null,
    foreign key (session_id) references sessions (id)
);

create table assets_chunks (
    asset_id integer not null,
    chunk_id integer not null,
    primary key (asset_id, chunk_id),
    foreign key (asset_id) references assets (id),
    foreign key (chunk_id) references chunks (id)
);

create table modules (
    id integer primary key,
    session_id integer not null,
    name text not null,
    size integer not null,
    foreign key (session_id) references sessions (id)
);

create table chunks_modules (
    chunk_id integer not null,
    module_id integer not null,
    primary key (chunk_id, module_id),
    foreign key (chunk_id) references chunks (id),
    foreign key (module_id) references modules (id)
);
"""

SCHEMA_VERSION = 1

Base = declarative_base()

"""
Create a custom context manager for SQLAlchemy session because worker is currently
stuck on SQLAlchemy version <1.4, and built in context manager for session is introduced
in 1.4 (which is also what codecov-api uses).
It is a lot of work to upgrade worker's SQLAlchemy version because it is too closely tied
into its postgres DB support.
When worker fully migrates to Django for postgres, we can simply upgrade the SQLAlchemy
version to support modern functionalities and delete this legacy code.
For now if the SQLAlchemy version is <1.4 it will go through the custom LegacySessionManager
context manager object to handle opening and closing its sessions.
"""


class LegacySessionManager:
    def __init__(self, session: DbSession):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, type, value, traceback):
        self.session.close()
        return True


def _use_modern_sqlalchemy_session_manager():
    try:
        version = sqlalchemy.__version__
        major = int(version.split(".")[0])
        minor = int(version.split(".")[1])
        return major >= 2 or (major == 1 and minor >= 4)
    except Exception as e:
        log.info(
            f"Can't determine which SQLAlchemy session manager to use, falling back to legacy: {e}"
        )
        return False


use_modern_sqlalchemy_session_manager = _use_modern_sqlalchemy_session_manager()


def get_db_session(path: str, auto_close: Optional[bool] = True) -> DbSession:
    engine = create_engine(f"sqlite:///{path}")
    Session = sessionmaker()
    Session.configure(bind=engine)
    session = Session()
    if not auto_close or use_modern_sqlalchemy_session_manager:
        return session
    else:
        return LegacySessionManager(session)


# table definitions for many-to-many joins
# (we're not creating models for these tables since they can be manipulated through each side of the join)

assets_chunks = Table(
    "assets_chunks",
    Base.metadata,
    Column("asset_id", ForeignKey("assets.id")),
    Column("chunk_id", ForeignKey("chunks.id")),
)

chunks_modules = Table(
    "chunks_modules",
    Base.metadata,
    Column("chunk_id", ForeignKey("chunks.id")),
    Column("module_id", ForeignKey("modules.id")),
)

# model definitions


class Bundle(Base):
    """
    A bundle is a top-level wrapper of various assets.  A large application
    may have multiple bundles being built and we'd like to track all of them
    separately.
    """

    __tablename__ = "bundles"

    id = Column(types.Integer, primary_key=True)
    name = Column(types.Text, nullable=False)


class Session(Base):
    """
    A session represents a single bundle stats file that we ingest.
    Multiple sessions are combined into a single database to form a full
    bundle report.
    """

    __tablename__ = "sessions"

    id = Column(types.Integer, primary_key=True)
    bundle_id = Column(types.Integer, ForeignKey("bundles.id"), nullable=False)
    info = Column(types.JSON)

    bundle = relationship("Bundle", backref=backref("sessions"))


class Metadata(Base):
    """
    Metadata about the bundle report.
    """

    __tablename__ = "metadata"

    key = Column(types.Text, primary_key=True)
    value = Column(types.JSON)


class AssetType(Enum):
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    STYLESHEET = "stylesheet"
    FONT = "font"
    IMAGE = "image"
    UNKNOWN = "unknown"

class Asset(Base):
    """
    These are the top-level artifacts that the bundling process produces.
    """

    __tablename__ = "assets"

    id = Column(types.Integer, primary_key=True)
    session_id = Column(types.Integer, ForeignKey("sessions.id"), nullable=False)
    name = Column(types.Text, nullable=False)
    normalized_name = Column(types.Text, nullable=False)
    size = Column(types.Integer, nullable=False)
    uuid = Column(types.Text, nullable=False)
    asset_type = Column(SQLAlchemyEnum(AssetType))
    session = relationship("Session", backref=backref("assets"))
    chunks = relationship(
        "Chunk", secondary=assets_chunks, back_populates="assets", cascade="all, delete"
    )


class Chunk(Base):
    """
    These are an intermediate form that I don't totally understand yet.
    """

    __tablename__ = "chunks"

    id = Column(types.Integer, primary_key=True)
    session_id = Column(types.Integer, ForeignKey("sessions.id"), nullable=False)
    external_id = Column(types.Text, nullable=False)
    unique_external_id = Column(types.Text, nullable=False)
    entry = Column(types.Boolean, nullable=False)
    initial = Column(types.Boolean, nullable=False)

    session = relationship("Session", backref=backref("chunks"))
    assets = relationship("Asset", secondary=assets_chunks, back_populates="chunks")
    modules = relationship(
        "Module",
        secondary=chunks_modules,
        back_populates="chunks",
        cascade="all, delete",
    )


class Module(Base):
    """
    These are the constituent modules that comprise an asset.
    """

    __tablename__ = "modules"

    id = Column(types.Integer, primary_key=True)
    session_id = Column(types.Integer, ForeignKey("sessions.id"), nullable=False)
    name = Column(types.Text, nullable=False)
    size = Column(types.Integer, nullable=False)

    session = relationship("Session", backref=backref("modules"))
    chunks = relationship(
        "Chunk",
        secondary=chunks_modules,
        back_populates="modules",
    )


class MetadataKey(Enum):
    SCHEMA_VERSION = "schema_version"
