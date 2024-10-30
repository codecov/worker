import contextvars
import logging
from dataclasses import asdict, dataclass, replace

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
    owner_id: int | None = None
    repo_name: str | None = None
    repo_id: int | None = None
    commit_sha: str | None = None
    commit_id: int | None = None

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
            incomplete_sha = self.commit_id is None or self.commit_sha is None
            incomplete_repo = self.repo_name is None or self.repo_id is None
            incomplete_owner = (
                self.owner_id is None
                or self.owner_username is None
                or self.owner_service is None
            )

            can_identify_commit = self.commit_id is not None or (
                self.commit_sha is not None and self.repo_id is not None
            )

            # commit_id or (commit_sha + repo_id) is enough to get everything else
            if can_identify_commit and (
                incomplete_sha or incomplete_repo or incomplete_owner
            ):
                if self.commit_id is not None:
                    commit = (
                        dbsession.query(Commit)
                        .filter(Commit.id_ == self.commit_id)
                        .first()
                    )
                else:
                    commit = (
                        dbsession.query(Commit)
                        .filter(
                            Commit.commitid == self.commit_sha,
                            Commit.repoid == self.repo_id,
                        )
                        .first()
                    )

                self.commit_id = commit.id_
                self.commit_sha = commit.commitid

                if incomplete_repo:
                    self.repo_id = commit.repository.repoid
                    self.repo_name = commit.repository.name

                if incomplete_owner:
                    self.owner_id = commit.repository.owner.ownerid
                    self.owner_username = commit.repository.owner.username
                    self.owner_service = commit.repository.owner.service

            # repo_id is enough to get repo and owner
            elif self.repo_id and (incomplete_repo or incomplete_owner):
                repo = (
                    dbsession.query(Repository)
                    .filter(Repository.repoid == self.repo_id)
                    .first()
                )
                self.repo_name = repo.name

                if incomplete_owner:
                    self.owner_id = repo.owner.ownerid
                    self.owner_username = repo.owner.username
                    self.owner_service = repo.owner.service

            # owner_id is just enough for owner
            elif self.owner_id and incomplete_owner:
                owner = (
                    dbsession.query(Owner)
                    .filter(Owner.ownerid == self.owner_id)
                    .first()
                )
                self.owner_username = owner.username
                self.owner_service = owner.service

        except Exception:
            log.exception("Failed to populate log context")

        self._populated_from_db = True

    def add_to_log_record(self, log_record: dict):
        log_record["context"] = self.as_dict()

    def add_to_sentry(self):
        d = self.as_dict()
        d.pop("sentry_trace_id", None)
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
