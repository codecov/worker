import logging

from database.enums import CommitErrorTypes
from database.models import Commit
from database.models.core import CommitError

log = logging.getLogger(__name__)


def save_bot_error(commit: Commit):
    try:
        db_session = commit.get_db_session()
        err = CommitError(
            commit=commit,
            error_code=CommitErrorTypes.Bot.value.REPO_BOT_INVALID.value,
            error_params={},
        )
        db_session.add(err)
        db_session.commit()

    except Exception as e:
        log.info("Error saving bot commit error -repo bot invalid-", e)
