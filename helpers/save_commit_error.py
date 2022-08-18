import logging

from database.enums import CommitErrorTypes
from database.models import Commit
from database.models.core import CommitError

log = logging.getLogger(__name__)


def save_repo_bot_error(commit: Commit):
    try:
        db_session = commit.get_db_session()
        code = CommitErrorTypes.Bot.value.REPO_BOT_INVALID.value
        error_exist = (
            db_session.query(CommitError)
            .filter_by(commit=commit, error_code=code)
            .first()
        )
        if len(commit.errors) == 0 or not error_exist:
            err = CommitError(
                commit=commit,
                error_code=code,
                error_params={},
            )
            db_session.add(err)
            db_session.commit()

    except:
        log.warning("Error saving bot commit error -repo bot invalid-")


def save_yaml_error(commit: Commit, code):
    try:
        db_session = commit.get_db_session()
        error_exist = (
            db_session.query(CommitError)
            .filter_by(commit=commit, error_code=code)
            .first()
        )
        if len(commit.errors) == 0 or not error_exist:
            err = CommitError(commit=commit, error_code=code, error_params={})
            db_session.add(err)
            db_session.commit()

    except:
        log.warning("Error saving yaml commit error")
