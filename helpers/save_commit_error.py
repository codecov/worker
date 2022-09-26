from database.models import Commit
from database.models.core import CommitError


def save_commit_error(commit: Commit, error_code, error_params=None):
    db_session = commit.get_db_session()
    error_exist = (
        db_session.query(CommitError)
        .filter_by(commit=commit, error_code=error_code)
        .first()
    )

    if error_params is None:
        error_params = {}

    if not error_exist:
        err = CommitError(
            commit=commit,
            error_code=error_code,
            error_params=error_params,
        )
        db_session.add(err)
        db_session.flush()
