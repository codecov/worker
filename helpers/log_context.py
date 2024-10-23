import contextvars
import logging
from dataclasses import dataclass, replace

from database.models.core import Commit, Repository

log = logging.getLogger("log_context")


@dataclass
class LogContext:
    """
    Class containing all the information we may want to add in logs and metrics.
    """

    task_name: str = "???"
    task_id: str = "???"

    _populated_from_db = False
    owner_id: int | None = None
    repo_id: int | None = None
    commit_sha: str | None = None
    commit_id: int | None = None

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
            if self.repo_id:
                if not self.owner_id:
                    self.owner_id = (
                        dbsession.query(Repository.ownerid)
                        .filter(Repository.repoid == self.repo_id)
                        .first()[0]
                    )

                if self.commit_sha and not self.commit_id:
                    self.commit_id = (
                        dbsession.query(Commit.id_)
                        .filter(
                            Commit.repoid == self.repo_id,
                            Commit.commitid == self.commit_sha,
                        )
                        .first()[0]
                    )
        except Exception:
            log.exception("Failed to populate log context")

        self._populated_from_db = True


_log_context = contextvars.ContextVar("log_context", default=LogContext())


def set_log_context(context: LogContext):
    """
    Overwrite whatever is currently in the log context.
    """
    _log_context.set(context)


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
