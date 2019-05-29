from database.base import CodecovBaseModel
from sqlalchemy import Column, types, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects import postgresql


class Owner(CodecovBaseModel):
    __tablename__ = 'owners'
    ownerid = Column(types.Integer, primary_key=True)
    service = Column(types.String(100))
    service_id = Column(types.Text)

    name = Column(types.String(100))
    email = Column(types.String(300))
    username = Column(types.String(100))
    plan_activated_users = Column(postgresql.ARRAY(types.Integer))
    admins = Column(postgresql.ARRAY(types.Integer))
    permission = Column(postgresql.ARRAY(types.Integer))
    free = Column(types.Integer)
    yaml = Column(postgresql.JSON)
    oauth_token = Column(types.Text)


class Repository(CodecovBaseModel):

    __tablename__ = 'repos'

    repoid = Column(types.Integer, primary_key=True)
    ownerid = Column(types.Integer, ForeignKey('owners.ownerid'))
    service_id = Column(types.Text)
    name = Column(types.Text)
    private = Column(types.Boolean)
    updatestamp = Column(types.DateTime)
    yaml = Column(postgresql.JSON)
    branch = Column(types.Text)
    hookid = Column(types.Text)

    owner = relationship(Owner)

    @property
    def service(self):
        return self.owner.service


class Commit(CodecovBaseModel):

    __tablename__ = 'commits'

    commitid = Column(types.Text, primary_key=True)
    repoid = Column(types.Integer, ForeignKey('repos.repoid'))
    author_id = Column('author', types.Integer, ForeignKey('owners.ownerid'))
    message = Column(types.Text)
    ci_passed = Column(types.Boolean)
    pullid = Column(types.Integer)
    totals = Column(postgresql.JSON)
    report = Column(postgresql.JSON)
    branch = Column(types.Text)
    parent_commit_id = Column('parent', types.Text)
    state = Column(types.String(256))

    author = relationship(Owner)
    repository = relationship(Repository)
