import random
import string
import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint, types
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import backref, relationship, validates
from sqlalchemy.schema import FetchedValue

import database.models
from database.base import CodecovBaseModel, MixinBaseClass
from database.enums import Decoration, Notification, NotificationState
from database.utils import ArchiveField
from helpers.config import should_write_data_to_storage_config_check


class User(CodecovBaseModel):
    __tablename__ = "users"
    id_ = Column("id", types.BigInteger, primary_key=True)

    # This field is case-insensitive but we don't have a way to represent that
    # here. Options to address:
    # - Upgrade sqlalchemy and use `postgresql.CITEXT(100)` as the field type
    # - Add a case-insensitive collation to postgres[1] and use it here + in `codecov-api`
    #
    # [1] https://www.postgresql.org/docs/current/collation.html
    email = Column(types.String(100), nullable=True)

    name = Column(types.String(100), nullable=True)
    is_staff = Column(types.Boolean, default=False)
    is_superuser = Column(types.Boolean, default=False)
    external_id = Column(postgresql.UUID(as_uuid=True), unique=True, default=uuid.uuid4)

    @validates("external_id")
    def validate_external_id(self, key, value):
        if self.external_id:
            raise ValueError("`external_id` cannot be modified")
        return value


class Owner(CodecovBaseModel):
    __tablename__ = "owners"
    ownerid = Column(types.Integer, primary_key=True)
    service = Column(types.String(100), nullable=False, server_default=FetchedValue())
    service_id = Column(types.Text, nullable=False, server_default=FetchedValue())

    name = Column(types.String(100), server_default=FetchedValue())
    email = Column(types.String(300), server_default=FetchedValue())
    username = Column(types.String(100), server_default=FetchedValue())
    plan_activated_users = Column(
        postgresql.ARRAY(types.Integer), server_default=FetchedValue()
    )
    # createstamp seems to be used by legacy to track first login
    # so we shouldn't touch this outside login
    createstamp = Column(types.DateTime, server_default=FetchedValue())
    admins = Column(postgresql.ARRAY(types.Integer), server_default=FetchedValue())
    permission = Column(postgresql.ARRAY(types.Integer), server_default=FetchedValue())
    organizations = Column(
        postgresql.ARRAY(types.Integer), server_default=FetchedValue()
    )
    free = Column(
        types.Integer, nullable=False, default=0, server_default=FetchedValue()
    )
    integration_id = Column(types.Integer, server_default=FetchedValue())
    yaml = Column(postgresql.JSON, server_default=FetchedValue())
    oauth_token = Column(types.Text, server_default=FetchedValue())
    avatar_url = Column(types.Text, server_default=FetchedValue())
    updatestamp = Column(types.DateTime, server_default=FetchedValue())
    parent_service_id = Column(types.Text, server_default=FetchedValue())
    plan_provider = Column(types.Text, server_default=FetchedValue())
    trial_start_date = Column(types.DateTime, server_default=FetchedValue())
    trial_end_date = Column(types.DateTime, server_default=FetchedValue())
    trial_status = Column(types.Text, server_default=FetchedValue())
    plan = Column(types.Text, server_default=FetchedValue())
    plan_user_count = Column(types.SmallInteger, server_default=FetchedValue())
    pretrial_users_count = Column(types.SmallInteger, server_default=FetchedValue())
    plan_auto_activate = Column(types.Boolean, server_default=FetchedValue())
    stripe_customer_id = Column(types.Text, server_default=FetchedValue())
    stripe_subscription_id = Column(types.Text, server_default=FetchedValue())
    onboarding_completed = Column(types.Boolean, default=False)
    bot_id = Column(
        "bot",
        types.Integer,
        ForeignKey("owners.ownerid"),
        server_default=FetchedValue(),
    )

    bot = relationship("Owner", remote_side=[ownerid])
    repositories = relationship(
        "Repository",
        back_populates="owner",
        foreign_keys="Repository.ownerid",
        cascade="all, delete",
        passive_deletes=True,
    )

    # TODO: Create association between `User` and `Owner` mirroring `codecov-api`
    # https://github.com/codecov/codecov-api/blob/204f7fd7e37896efe0259e4bc91aad20601087e0/codecov_auth/models.py#L196-L202

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
    deleted = Column(types.Boolean, nullable=False, default=False)
    branch = Column(types.Text)
    image_token = Column(
        types.Text,
        default=lambda: "".join(
            random.choice(string.ascii_uppercase + string.digits) for _ in range(10)
        ),
    )
    language = Column(types.Text)
    hookid = Column(types.Text)
    webhook_secret = Column(types.Text)
    activated = Column(types.Boolean, default=False)
    using_integration = Column(types.Boolean)

    owner = relationship(Owner, foreign_keys=[ownerid], back_populates="repositories")
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
    state = Column(types.String(256))
    timestamp = Column(types.DateTime, nullable=False)
    updatestamp = Column(types.DateTime, nullable=True)
    totals = Column(postgresql.JSON)

    author = relationship(Owner)
    repository = relationship(Repository, backref=backref("commits", cascade="delete"))
    notifications = relationship(
        "CommitNotification",
        backref=backref("commits"),
        cascade="all, delete",
        passive_deletes=True,
    )
    reports_list = relationship(
        "CommitReport",
        back_populates="commit",
        cascade="all, delete",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"Commit<{self.commitid}@repo<{self.repoid}>>"

    def get_parent_commit(self):
        db_session = self.get_db_session()
        return (
            db_session.query(Commit)
            .filter_by(repoid=self.repoid, commitid=self.parent_commit_id)
            .first()
        )

    @property
    def report(self):
        db_session = self.get_db_session()
        return (
            db_session.query(database.models.reports.CommitReport)
            .filter_by(commit_id=self.id_, code=None)
            .first()
        )

    @property
    def id(self):
        return self.id_

    @property
    def external_id(self):
        return self.commitid

    def get_repository(self):
        return self.repository

    def get_commitid(self):
        return self.commitid

    def should_write_to_storage(self) -> bool:
        if self.repository is None or self.repository.owner is None:
            return False
        is_codecov_repo = self.repository.owner.username == "codecov"
        return should_write_data_to_storage_config_check(
            "commit_report", is_codecov_repo, self.repository.repoid
        )

    # Use custom JSON to properly serialize custom data classes on reports
    _report_json = Column("report", postgresql.JSON)
    _report_json_storage_path = Column("report_storage_path", types.Text, nullable=True)
    report_json = ArchiveField(
        should_write_to_storage_fn=should_write_to_storage,
        default_value_class=dict,
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


class LoginSession(CodecovBaseModel):
    __tablename__ = "sessions"

    sessionid = Column(types.Integer, primary_key=True)
    token = Column(postgresql.UUID(as_uuid=True))
    name = Column(types.Text)
    ownerid = Column(types.Integer, ForeignKey("owners.ownerid"))
    session_type = Column("type", types.Text)
    lastseen = Column(types.DateTime(timezone=True))
    useragent = Column(types.Text)
    ip = Column(types.Text)


class Pull(CodecovBaseModel):
    __tablename__ = "pulls"

    id_ = Column("id", types.BigInteger, primary_key=True)
    repoid = Column(types.Integer, ForeignKey("repos.repoid"))
    pullid = Column(types.Integer, nullable=False)
    issueid = Column(types.Integer)
    updatestamp = Column(
        types.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    state = Column(types.Text, nullable=False, default="open")
    title = Column(types.Text)
    base = Column(types.Text)
    user_provided_base_sha = Column(types.Text)
    compared_to = Column(types.Text)
    head = Column(types.Text)
    commentid = Column(types.Text)
    diff = Column(postgresql.JSON)
    flare = Column(postgresql.JSON)
    author_id = Column("author", types.Integer, ForeignKey("owners.ownerid"))
    behind_by = Column(types.Integer)
    behind_by_commit = Column(types.Text)

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

    def get_repository(self):
        return self.repository

    def get_commitid(self):
        return None

    @property
    def external_id(self):
        return self.pullid

    @property
    def id(self):
        return self.id_

    def should_write_to_storage(self) -> bool:
        if self.repository is None or self.repository.owner is None:
            return False
        is_codecov_repo = self.repository.owner.username == "codecov"
        return should_write_data_to_storage_config_check(
            master_switch_key="pull_flare",
            is_codecov_repo=is_codecov_repo,
            repoid=self.repository.repoid,
        )

    _flare = Column("flare", postgresql.JSON)
    _flare_storage_path = Column("flare_storage_path", types.Text, nullable=True)
    flare = ArchiveField(
        should_write_to_storage_fn=should_write_to_storage, default_value_class=dict
    )


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
        Index("notifications_commit_id", "commit_id"),
        UniqueConstraint(
            "commit_id",
            "notification_type",
            name="commit_notifications_commit_id_notification_type",
        ),
    )

    def __repr__(self):
        return f"Notification<{self.notification_type}@commit<{self.commit_id}>>"


class CompareCommit(MixinBaseClass, CodecovBaseModel):
    __tablename__ = "compare_commitcomparison"

    base_commit_id = Column(types.BigInteger, ForeignKey("commits.id"))
    base_commit = relationship(Commit, foreign_keys=[base_commit_id])
    compare_commit_id = Column(types.BigInteger, ForeignKey("commits.id"))
    compare_commit = relationship(Commit, foreign_keys=[compare_commit_id])
    report_storage_path = Column(types.String(150))
    patch_totals = Column(postgresql.JSON)
    state = Column(types.Text)
    error = Column(types.Text)

    __table_args__ = (
        Index("compare_commitcomparison_base_commit_id_cf53c1d9", "base_commit_id"),
        Index(
            "compare_commitcomparison_compare_commit_id_3ea19610", "compare_commit_id"
        ),
        UniqueConstraint(
            "base_commit_id",
            "compare_commit_id",
            name="unique_comparison_between_commit",
        ),
    )

    def __repr__(self):
        return f"CompareCommit<{self.base_commit_id}...{self.compare_commit_id}>"


class CommitError(CodecovBaseModel, MixinBaseClass):
    __tablename__ = "core_commiterror"

    commit_id = Column(types.BigInteger, ForeignKey("commits.id"))
    commit = relationship(Commit, foreign_keys=[commit_id], backref="errors")
    error_code = Column(types.String(100), nullable=True)
    error_params = Column(postgresql.JSON, default=dict)


class OrganizationLevelToken(MixinBaseClass, CodecovBaseModel):
    __tablename__ = "codecov_auth_organizationleveltoken"

    ownerid = Column(types.Integer, ForeignKey("owners.ownerid"))
    owner = relationship(Owner, foreign_keys=[ownerid])
    token = Column(postgresql.UUID)
    valid_until = Column(types.DateTime)
    token_type = Column(types.String)


class Constants(CodecovBaseModel):
    __tablename__ = "constants"

    key = Column(types.String, primary_key=True)
    value = Column(types.String)
