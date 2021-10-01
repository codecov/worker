from database.enums import CompareCommitState
from database.tests.factories.core import CommitFactory, CompareCommitFactory
from services.comparison import get_or_create_comparison


class TestGetOrCreateComparison(object):
    def test_get_or_create_existing_comparison(self, dbsession):
        existing_comparison = CompareCommitFactory.create()
        dbsession.add(existing_comparison)
        dbsession.flush()

        comparison = get_or_create_comparison(
            dbsession,
            existing_comparison.base_commit,
            existing_comparison.compare_commit,
        )
        assert comparison == existing_comparison
        assert comparison.state == CompareCommitState.pending.value
        assert comparison.error is None

    def test_get_or_create_new_comparison(self, dbsession):
        base_commit = CommitFactory()
        commit = CommitFactory()
        dbsession.commit()
        comparison = get_or_create_comparison(dbsession, base_commit, commit)
        dbsession.flush()
        assert comparison.state == CompareCommitState.pending.value
        assert comparison.base_commit == base_commit
        assert comparison.compare_commit == commit
