from database.models import Branch, Commit, CommitNotification, Owner, Pull, Repository
from database.tests.factories import (
    BranchFactory,
    CommitFactory,
    CommitNotificationFactory,
    CompareCommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)


class TestReprModels(object):
    def test_owner_repr(self, dbsession):
        simple_owner = Owner()
        assert "Owner<None@service<None>>" == repr(simple_owner)
        factoried_owner = OwnerFactory.create(service="github")
        assert "Owner<None@service<github>>" == repr(factoried_owner)
        dbsession.add(factoried_owner)
        dbsession.flush()
        dbsession.refresh(factoried_owner)
        assert f"Owner<{factoried_owner.ownerid}@service<github>>" == repr(
            factoried_owner
        )

    def test_repo_repr(self, dbsession):
        simple_repo = Repository()
        assert "Repo<None>" == repr(simple_repo)
        factoried_repo = RepositoryFactory.create()
        assert "Repo<None>" == repr(factoried_repo)
        dbsession.add(factoried_repo)
        dbsession.flush()
        dbsession.refresh(factoried_repo)
        assert f"Repo<{factoried_repo.repoid}>" == repr(factoried_repo)

    def test_commit_repr(self, dbsession):
        simple_commit = Commit()
        assert "Commit<None@repo<None>>" == repr(simple_commit)
        factoried_commit = CommitFactory.create(
            commitid="327993f5d81eda4bac19ea6090fe68c8eb313066"
        )
        assert "Commit<327993f5d81eda4bac19ea6090fe68c8eb313066@repo<None>>" == repr(
            factoried_commit
        )
        dbsession.add(factoried_commit)
        dbsession.flush()
        dbsession.refresh(factoried_commit)
        assert (
            f"Commit<327993f5d81eda4bac19ea6090fe68c8eb313066@repo<{factoried_commit.repoid}>>"
            == repr(factoried_commit)
        )

    def test_branch_repr(self, dbsession):
        simple_branch = Branch()
        assert "Branch<None@repo<None>>" == repr(simple_branch)
        factoried_branch = BranchFactory.create(branch="thisoakbranch")
        assert "Branch<thisoakbranch@repo<None>>" == repr(factoried_branch)
        dbsession.add(factoried_branch)
        dbsession.flush()
        dbsession.refresh(factoried_branch)
        assert f"Branch<thisoakbranch@repo<{factoried_branch.repoid}>>" == repr(
            factoried_branch
        )

    def test_pull_repr(self, dbsession):
        simple_pull = Pull()
        assert "Pull<None@repo<None>>" == repr(simple_pull)
        factoried_pull = PullFactory.create()
        assert f"Pull<{factoried_pull.pullid}@repo<None>>" == repr(factoried_pull)
        dbsession.add(factoried_pull)
        dbsession.flush()
        dbsession.refresh(factoried_pull)
        assert f"Pull<{factoried_pull.pullid}@repo<{factoried_pull.repoid}>>" == repr(
            factoried_pull
        )

    def test_notification_repr(self, dbsession):
        simple_notification = CommitNotification()
        assert "Notification<None@commit<None>>" == repr(simple_notification)
        factoried_notification = CommitNotificationFactory.create()
        assert (
            f"Notification<{factoried_notification.notification_type}@commit<{factoried_notification.commit_id}>>"
            == repr(factoried_notification)
        )
        dbsession.add(factoried_notification)
        dbsession.flush()
        dbsession.refresh(factoried_notification)
        assert (
            f"Notification<{factoried_notification.notification_type}@commit<{factoried_notification.commit_id}>>"
            == repr(factoried_notification)
        )

    def test_commit_compare_repr(self, dbsession):
        compare_commit = CompareCommitFactory()
        assert "CompareCommit<None...None>" == repr(compare_commit)

    def test_commit_notified(self, dbsession):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        assert commit.notified is None
        commit.notified = True
        dbsession.flush()
        dbsession.refresh(commit)
        assert commit.notified is True


class TestPullModel(object):
    def test_updatestamp_update(self, dbsession):
        factoried_pull = PullFactory.create(updatestamp=None)
        assert factoried_pull.updatestamp is None
        dbsession.add(factoried_pull)
        dbsession.flush()
        assert factoried_pull.updatestamp is not None
        val = factoried_pull.updatestamp
        factoried_pull.title = "Super Mario Bros"
        dbsession.flush()
        assert factoried_pull.updatestamp is not None
        assert factoried_pull.updatestamp > val
