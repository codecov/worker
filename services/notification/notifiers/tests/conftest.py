import pytest
from covreports.reports.resources import Report, ReportFile, ReportLine
from covreports.utils.sessions import Session

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.notification.types import FullCommit, Comparison


def get_small_report():
    report = Report()
    first_file = ReportFile("file_1.go")
    first_file.append(1, ReportLine(coverage=1, sessions=[[0, 1]], complexity=(11, 20)))
    first_file.append(3, ReportLine(coverage=0, sessions=[[0, 1]]))
    first_file.append(5, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(6, ReportLine(coverage=0, sessions=[[0, 1]]))
    second_file = ReportFile("file_2.py")
    second_file.append(12, ReportLine(coverage=1, sessions=[[0, 1]]))
    second_file.append(51, ReportLine(coverage=0, sessions=[[0, 1]]))
    report.append(first_file)
    report.append(second_file)
    report.add_session(Session(flags=["integration"]))
    return report


@pytest.fixture
def small_report():
    return get_small_report()


@pytest.fixture
def sample_report_without_flags():
    report = Report()
    first_file = ReportFile("file_1.go")
    first_file.append(1, ReportLine(coverage=1, sessions=[[0, 1]], complexity=(10, 2)))
    first_file.append(2, ReportLine(coverage=0, sessions=[[0, 1]]))
    first_file.append(3, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(5, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(6, ReportLine(coverage=0, sessions=[[0, 1]]))
    first_file.append(8, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(9, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(10, ReportLine(coverage=0, sessions=[[0, 1]]))
    second_file = ReportFile("file_2.py")
    second_file.append(12, ReportLine(coverage=1, sessions=[[0, 1]]))
    second_file.append(51, ReportLine(coverage="1/2", type="b", sessions=[[0, 1]]))
    report.append(first_file)
    report.append(second_file)
    report.add_session(Session(flags=None))
    return report


@pytest.fixture
def sample_report():
    report = Report()
    first_file = ReportFile("file_1.go")
    first_file.append(1, ReportLine(coverage=1, sessions=[[0, 1]], complexity=(10, 2)))
    first_file.append(2, ReportLine(coverage=0, sessions=[[0, 1]]))
    first_file.append(3, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(5, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(6, ReportLine(coverage=0, sessions=[[0, 1]]))
    first_file.append(8, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(9, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(10, ReportLine(coverage=0, sessions=[[0, 1]]))
    second_file = ReportFile("file_2.py")
    second_file.append(12, ReportLine(coverage=1, sessions=[[0, 1]]))
    second_file.append(51, ReportLine(coverage="1/2", type="b", sessions=[[0, 1]]))
    report.append(first_file)
    report.append(second_file)
    report.add_session(Session(flags=["unit"]))
    return report


@pytest.fixture
def create_sample_comparison(dbsession, request, sample_report):
    def _comparison(service="github", username="codecov-test"):
        repository = RepositoryFactory.create(
            owner__username=username, owner__service=service,
        )
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(repository=repository)
        head_commit = CommitFactory.create(repository=repository, branch="new_branch")
        pull = PullFactory.create(
            repository=repository, base=base_commit.commitid, head=head_commit.commitid
        )
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        repository = base_commit.repository
        base_full_commit = FullCommit(commit=base_commit, report=get_small_report())
        head_full_commit = FullCommit(commit=head_commit, report=sample_report)
        return Comparison(head=head_full_commit, base=base_full_commit, pull=pull)

    return _comparison


@pytest.fixture
def sample_comparison(dbsession, request, sample_report):
    repository = RepositoryFactory.create(owner__username=request.node.name,)
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    pull = PullFactory.create(
        repository=repository, base=base_commit.commitid, head=head_commit.commitid
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(commit=base_commit, report=get_small_report())
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    return Comparison(head=head_full_commit, base=base_full_commit, pull=pull)


@pytest.fixture
def sample_comparison_negative_change(dbsession, request, sample_report):
    repository = RepositoryFactory.create(owner__username=request.node.name,)
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    pull = PullFactory.create(
        repository=repository, base=base_commit.commitid, head=head_commit.commitid
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(commit=base_commit, report=sample_report)
    head_full_commit = FullCommit(commit=head_commit, report=get_small_report())
    return Comparison(head=head_full_commit, base=base_full_commit, pull=pull)


@pytest.fixture
def sample_comparison_without_pull(dbsession, request, sample_report):
    repository = RepositoryFactory.create(owner__username=request.node.name,)
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(commit=base_commit, report=get_small_report())
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    return Comparison(head=head_full_commit, base=base_full_commit, pull=None)


@pytest.fixture
def sample_comparison_without_base_report(dbsession, request, sample_report):
    repository = RepositoryFactory.create(owner__username=request.node.name,)
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    pull = PullFactory.create(
        repository=repository, base=base_commit.commitid, head=head_commit.commitid
    )
    dbsession.add(head_commit)
    dbsession.add(base_commit)
    dbsession.add(pull)
    dbsession.flush()
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    base_full_commit = FullCommit(commit=base_commit, report=None)
    return Comparison(head=head_full_commit, base=base_full_commit, pull=pull)


@pytest.fixture
def sample_comparison_without_base_with_pull(dbsession, request, sample_report):
    repository = RepositoryFactory.create(owner__username=request.node.name,)
    dbsession.add(repository)
    dbsession.flush()
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    pull = PullFactory.create(
        repository=repository, base="base_commitid", head=head_commit.commitid
    )
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    base_full_commit = FullCommit(commit=None, report=None)
    return Comparison(head=head_full_commit, base=base_full_commit, pull=pull)
