import contextvars
import logging
from dataclasses import asdict, dataclass, field, replace

import sentry_sdk
from sentry_sdk import get_current_span

from database.models.core import Commit, Owner, Repository

log = logging.getLogger("log_context")


@dataclass
class LogContext:
    """
    Class containing all the information we may want to add in logs and metrics.
    """

    task_name: str = "???"
    task_id: str = "???"

    _populated_from_db = False
    owner_username: str | None = None
    owner_service: str | None = None
    owner_plan: str | None = None
    owner_id: int | None = None
    repo_name: str | None = None
    repo_id: int | None = None
    commit_sha: str | None = None
    commit_id: int | None = None

    checkpoints_data: dict = field(default_factory=lambda: {})

    @property
    def sentry_trace_id(self):
        if span := get_current_span():
            return span.trace_id
        return None

    def as_dict(self):
        d = asdict(self)
        d.pop("_populated_from_db", None)
        d["sentry_trace_id"] = self.sentry_trace_id
        return d

    def populate_from_sqlalchemy(self, dbsession):
        """
        Attempt to use the information we have to fill in other context fields. For
        example, if we have `self.repo_id` but not `self.owner_id`, we can look up
        the latter in the database.

        Ignore exceptions; no need to fail a task for a missing context field.
        """
        if self._populated_from_db:
            return

        try:
            can_identify_commit = self.commit_id is not None or (
                self.commit_sha is not None and self.repo_id is not None
            )

            # commit_id or (commit_sha + repo_id) is enough to get everything else
            if can_identify_commit:
                query = (
                    dbsession.query(
                        Commit.id_,
                        Commit.commitid,
                        Repository.repoid,
                        Repository.name,
                        Owner.ownerid,
                        Owner.username,
                        Owner.service,
                        Owner.plan,
                    )
                    .join(Commit.repository)
                    .join(Repository.owner)
                )

                if self.commit_id is not None:
                    query = query.filter(Commit.id_ == self.commit_id)
                else:
                    query = query.filter(
                        Commit.commitid == self.commit_sha,
                        Commit.repoid == self.repo_id,
                    )

                (
                    self.commit_id,
                    self.commit_sha,
                    self.repo_id,
                    self.repo_name,
                    self.owner_id,
                    self.owner_username,
                    self.owner_service,
                    self.owner_plan,
                ) = query.first()

            # repo_id is enough to get repo and owner
            elif self.repo_id:
                query = (
                    dbsession.query(
                        Repository.name,
                        Owner.ownerid,
                        Owner.username,
                        Owner.service,
                        Owner.plan,
                    )
                    .join(Repository.owner)
                    .filter(Repository.repoid == self.repo_id)
                )

                (
                    self.repo_name,
                    self.owner_id,
                    self.owner_username,
                    self.owner_service,
                    self.owner_plan,
                ) = query.first()

            # owner_id is just enough for owner
            elif self.owner_id:
                query = dbsession.query(
                    Owner.username, Owner.service, Owner.plan
                ).filter(Owner.ownerid == self.owner_id)

                (self.owner_username, self.owner_service, self.owner_plan) = (
                    query.first()
                )

        except Exception:
            log.exception("Failed to populate log context")

        self._populated_from_db = True

    def add_to_log_record(self, log_record: dict):
        d = self.as_dict()
        d.pop("checkpoints_data", None)
        log_record["context"] = d

    def add_to_sentry(self):
        d = self.as_dict()
        d.pop("sentry_trace_id", None)
        d.pop("checkpoints_data", None)
        sentry_sdk.set_tags(d)


_log_context = contextvars.ContextVar("log_context", default=LogContext())


def set_log_context(context: LogContext):
    """
    Overwrite whatever is currently in the log context. Also sets tags in the
    Sentry SDK appropriately.
    """
    _log_context.set(context)
    context.add_to_sentry()


def update_log_context(context: dict):
    """
    Add new fields to the log context without removing old ones.
    """
    current_context: LogContext = _log_context.get()
    new_context = replace(current_context, **context)
    set_log_context(new_context)


def get_log_context() -> LogContext:
    """
    Access the log context.
    """
    return _log_context.get()
