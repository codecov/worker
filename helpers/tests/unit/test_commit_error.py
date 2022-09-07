from database.enums import CommitErrorTypes
from database.tests.factories import CommitFactory
from helpers.save_commit_error import save_commit_error


class TestSaveCommitError(object):
    def test_save_commit_error(self, mocker, dbsession):
        commit = CommitFactory.create()
        dbsession.add(commit)

        save_commit_error(commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value)

        assert commit.errors
        assert len(commit.errors) == 1

    def test_save_commit_error_already_saved(self, mocker, dbsession):
        commit = CommitFactory.create()
        dbsession.add(commit)

        save_commit_error(commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value)
        save_commit_error(commit, error_code=CommitErrorTypes.REPO_BOT_INVALID.value)

        assert len(commit.errors) == 1
