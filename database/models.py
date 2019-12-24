from database.base import CodecovBaseModel
from sqlalchemy import Column, types, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy.dialects import postgresql
from sqlalchemy import UniqueConstraint, Index


class Owner(CodecovBaseModel):
    __tablename__ = 'owners'
    ownerid = Column(types.Integer, primary_key=True)
    service = Column(types.String(100), nullable=False)
    service_id = Column(types.Text, nullable=False)

    name = Column(types.String(100))
    email = Column(types.String(300))
    username = Column(types.String(100))
    plan_activated_users = Column(postgresql.ARRAY(types.Integer))
    admins = Column(postgresql.ARRAY(types.Integer))
    permission = Column(postgresql.ARRAY(types.Integer))
    organizations = Column(postgresql.ARRAY(types.Integer))
    free = Column(types.Integer, nullable=False, default=0)
    integration_id = Column(types.Integer)
    yaml = Column(postgresql.JSON)
    oauth_token = Column(types.Text)
    avatar_url = Column(types.Text)
    updatestamp = Column(types.DateTime)
    parent_service_id = Column(types.Text)
    plan_provider = Column(types.Text)
    bot_id = Column('bot', types.Integer, ForeignKey('owners.ownerid'))

    bot = relationship('Owner', remote_side=[ownerid])

    __table_args__ = (
        Index('owner_service_ids', 'service', 'service_id', unique=True),
        Index('owner_service_username', 'service', 'username', unique=True),
    )

    @property
    def slug(self):
        return self.username.replace(':', '/')


class Repository(CodecovBaseModel):

    __tablename__ = 'repos'

    repoid = Column(types.Integer, primary_key=True)
    ownerid = Column(types.Integer, ForeignKey('owners.ownerid'))
    bot_id = Column('bot', types.Integer, ForeignKey('owners.ownerid'))
    service_id = Column(types.Text)
    name = Column(types.Text)
    private = Column(types.Boolean)
    updatestamp = Column(types.DateTime)
    yaml = Column(postgresql.JSON)
    branch = Column(types.Text)
    language = Column(types.Text)
    hookid = Column(types.Text)
    using_integration = Column(types.Boolean)

    owner = relationship(Owner, foreign_keys=[ownerid], backref=backref("owners", cascade="delete"))
    bot = relationship(Owner, foreign_keys=[bot_id])

    __table_args__ = (
        Index('repos_slug', 'ownerid', 'name', unique=True),
        Index('repos_service_ids', 'ownerid', 'service_id', unique=True),
    )

    @property
    def slug(self):
        return f"{self.owner.slug}/{self.name}"

    @property
    def service(self):
        return self.owner.service


class Commit(CodecovBaseModel):

    __tablename__ = 'commits'

    author_id = Column('author', types.Integer, ForeignKey('owners.ownerid'))
    branch = Column(types.Text)
    ci_passed = Column(types.Boolean)
    commitid = Column(types.Text, primary_key=True)
    message = Column(types.Text)
    merged = Column(types.Boolean)
    parent_commit_id = Column('parent', types.Text)
    pullid = Column(types.Integer)
    repoid = Column(types.Integer, ForeignKey('repos.repoid'), primary_key=True)
    report_json = Column("report", postgresql.JSON)
    state = Column(types.String(256))
    timestamp = Column(types.DateTime, nullable=False)
    totals = Column(postgresql.JSON)

    author = relationship(Owner)
    repository = relationship(Repository, backref=backref("commits", cascade="delete"))


class Branch(CodecovBaseModel):

    __tablename__ = 'branches'

    repoid = Column(types.Integer, ForeignKey('repos.repoid'), primary_key=True)
    updatestamp = Column(types.DateTime)
    branch = Column(types.Text, nullable=False)
    base = Column(types.Text)
    head = Column(types.Text, nullable=False)
    authors = Column(postgresql.ARRAY(types.Integer))

    repository = relationship(Repository, backref=backref("branches", cascade="delete"))

    __table_args__ = (
        Index('branches_repoid_branch', 'repoid', 'branch', unique=True),
    )


class Pull(CodecovBaseModel):

    __tablename__ = 'pulls'

    repoid = Column(types.Integer, ForeignKey('repos.repoid'), primary_key=True)
    pullid = Column(types.Integer, nullable=False)
    issueid = Column(types.Integer)
    updatestamp = Column(types.DateTime)
    state = Column(types.Text, nullable=False, default='open')
    title = Column(types.Text)
    base = Column(types.Text)
    compared_to = Column(types.Text)
    head = Column(types.Text)
    commentid = Column(types.Text)
    diff = Column(postgresql.JSON)
    flare = Column(postgresql.JSON)
    author_id = Column('author', types.Integer, ForeignKey('owners.ownerid'))

    author = relationship(Owner)
    repository = relationship(Repository, backref=backref("pulls", cascade="delete"))

    __table_args__ = (
        Index('pulls_repoid_pullid', 'repoid', 'pullid', unique=True),
    )
