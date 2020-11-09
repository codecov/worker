import random
import string
from datetime import datetime

from database.base import CodecovBaseModel
from database.enums import Notification, NotificationState, Decoration
from sqlalchemy import Column, types, ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import relationship, backref
from sqlalchemy.dialects import postgresql
from sqlalchemy import UniqueConstraint, Index


class Owner(CodecovBaseModel):
    __tablename__ = "owners"
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
    plan = Column(types.Text)
    plan_user_count = Column(types.SmallInteger)
    plan_auto_activate = Column(types.Boolean)
    stripe_customer_id = Column(types.Text)
    stripe_subscription_id = Column(types.Text)
    bot_id = Column("bot", types.Integer, ForeignKey("owners.ownerid"))

    bot = relationship("Owner", remote_side=[ownerid])

    __table_args__ = (
        Index("owner_service_ids", "service", "service_id", unique=True),
        Index("owner_service_username", "service", "username", unique=True),
    )

    @property
    def slug(self):
        return self.username

    def __repr__(self):
        return f"Owner<{self.ownerid}@service<{self.service}>>"


class Repository(CodecovBaseModel):

    __tablename__ = "repos"

    repoid = Column(types.Integer, primary_key=True)
    ownerid = Column(types.Integer, ForeignKey("owners.ownerid"))
    bot_id = Column("bot", types.Integer, ForeignKey("owners.ownerid"))
    service_id = Column(types.Text)
    name = Column(types.Text)
    private = Column(types.Boolean)
    updatestamp = Column(types.DateTime)
    yaml = Column(postgresql.JSON)
    deleted = Column(types.Boolean)
    branch = Column(types.Text)
    image_token = Column(
        types.Text,
        default=lambda: "".join(
            random.choice(string.ascii_uppercase + string.digits) for _ in range(10)
        ),
    )
    language = Column(types.Text)
    hookid = Column(types.Text)
    activated = Column(types.Boolean, default=False)
    using_integration = Column(types.Boolean)
    cache_do_not_use = Column("cache", postgresql.JSON)

    owner = relationship(
        Owner, foreign_keys=[ownerid], backref=backref("owners", cascade="delete")
    )
    bot = relationship(Owner, foreign_keys=[bot_id])

    __table_args__ = (
        Index("repos_slug", "ownerid", "name", unique=True),
        Index("repos_service_ids", "ownerid", "service_id", unique=True),
    )

    @property
    def slug(self):
        return f"{self.owner.slug}/{self.name}"

    @property
    def service(self):
        return self.owner.service

    def __repr__(self):
        return f"Repo<{self.repoid}>"


class Commit(CodecovBaseModel):

    __tablename__ = "commits"

    id_ = Column("id", types.BigInteger, primary_key=True)
    author_id = Column("author", types.Integer, ForeignKey("owners.ownerid"))
    branch = Column(types.Text)
    ci_passed = Column(types.Boolean)
    commitid = Column(types.Text)
    deleted = Column(types.Boolean)
    message = Column(types.Text)
    notified = Column(types.Boolean)
    merged = Column(types.Boolean)
    parent_commit_id = Column("parent", types.Text)
    pullid = Column(types.Integer)
    repoid = Column(types.Integer, ForeignKey("repos.repoid"))
    report_json = Column("report", postgresql.JSON)
    state = Column(types.String(256))
    timestamp = Column(types.DateTime, nullable=False)
    updatestamp = Column(types.DateTime, nullable=True)
    totals = Column(postgresql.JSON)

    author = relationship(Owner)
    repository = relationship(Repository, backref=backref("commits", cascade="delete"))
    notifications = relationship(
        "CommitNotification", backref=backref("commits", cascade="delete")
    )
    report = relationship("CommitReport", uselist=False, back_populates="commit")

    def __repr__(self):
        return f"Commit<{self.commitid}@repo<{self.repoid}>>"

    def get_parent_commit(self):
        db_session = self.get_db_session()
        return (
            db_session.query(Commit)
            .filter_by(repoid=self.repoid, commitid=self.parent_commit_id)
            .first()
        )


class Branch(CodecovBaseModel):

    __tablename__ = "branches"

    repoid = Column(types.Integer, ForeignKey("repos.repoid"), primary_key=True)
    updatestamp = Column(types.DateTime)
    branch = Column(types.Text, nullable=False, primary_key=True)
    base = Column(types.Text)
    head = Column(types.Text, nullable=False)
    authors = Column(postgresql.ARRAY(types.Integer))

    repository = relationship(Repository, backref=backref("branches", cascade="delete"))

    __table_args__ = (Index("branches_repoid_branch", "repoid", "branch", unique=True),)

    def __repr__(self):
        return f"Branch<{self.branch}@repo<{self.repoid}>>"


class Pull(CodecovBaseModel):

    __tablename__ = "pulls"

    repoid = Column(types.Integer, ForeignKey("repos.repoid"), primary_key=True)
    pullid = Column(types.Integer, nullable=False, primary_key=True)
    issueid = Column(types.Integer)
    updatestamp = Column(types.DateTime)
    state = Column(types.Text, nullable=False, default="open")
    title = Column(types.Text)
    base = Column(types.Text)
    compared_to = Column(types.Text)
    head = Column(types.Text)
    commentid = Column(types.Text)
    diff = Column(postgresql.JSON)
    flare = Column(postgresql.JSON)
    author_id = Column("author", types.Integer, ForeignKey("owners.ownerid"))

    author = relationship(Owner)
    repository = relationship(Repository, backref=backref("pulls", cascade="delete"))

    __table_args__ = (Index("pulls_repoid_pullid", "repoid", "pullid", unique=True),)

    def __repr__(self):
        return f"Pull<{self.pullid}@repo<{self.repoid}>>"

    def get_head_commit(self):
        return (
            self.get_db_session()
            .query(Commit)
            .filter_by(repoid=self.repoid, commitid=self.head)
            .first()
        )

    def get_comparedto_commit(self):
        return (
            self.get_db_session()
            .query(Commit)
            .filter_by(repoid=self.repoid, commitid=self.compared_to)
            .first()
        )

    def get_head_commit_notifications(self):
        head_commit = self.get_head_commit()
        if head_commit:
            return (
                self.get_db_session()
                .query(CommitNotification)
                .filter_by(commit_id=head_commit.id_)
                .all()
            )
        return []


class CommitNotification(CodecovBaseModel):

    __tablename__ = "commit_notifications"

    id_ = Column("id", types.BigInteger, primary_key=True)
    commit_id = Column(types.BigInteger, ForeignKey("commits.id"))
    notification_type = Column(
        postgresql.ENUM(Notification, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    decoration_type = Column(
        postgresql.ENUM(Decoration, values_callable=lambda x: [e.value for e in x])
    )
    created_at = Column(types.DateTime, default=datetime.now())
    updated_at = Column(types.DateTime, default=datetime.now(), onupdate=datetime.now())
    state = Column(
        postgresql.ENUM(
            NotificationState, values_callable=lambda x: [e.value for e in x]
        )
    )

    commit = relationship(Commit, foreign_keys=[commit_id])

    __table_args__ = (
        Index("notifications_commit_id", "commit_id",),
        UniqueConstraint(
            "commit_id",
            "notification_type",
            name="commit_notifications_commit_id_notification_type",
        ),
    )

    def __repr__(self):
        return f"Notification<{self.notification_type}@commit<{self.commit_id}>>"
