import pytest
from covreports.resources import Report, ReportFile, ReportLine

from database.tests.factories import CommitFactory, PullRequestFactory, RepositoryFactory
from services.notification.types import FullCommit, Comparison


@pytest.fixture
def sample_report():
    report = Report()
    first_file = ReportFile('file_1.go')
    first_file.append(1, ReportLine(coverage=1, sessions=[[0, 1]]))
    first_file.append(2, ReportLine(coverage=0, sessions=[[0, 1]]))
    first_file.append(3, ReportLine(coverage=1, sessions=[[0, 1]]))
    second_file = ReportFile('file_2.py')
    second_file.append(12, ReportLine(coverage=1, sessions=[[0, 1]]))
    second_file.append(51, ReportLine(coverage='1/2', type='b', sessions=[[0, 1]]))
    report.append(first_file)
    report.append(second_file)
    return report


@pytest.fixture
def sample_comparison(dbsession, request, sample_report):
    repository = RepositoryFactory.create(
        owner__username=request.node.name,
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository)
    head_commit = CommitFactory.create(repository=repository, branch='new_branch')
    pull = PullRequestFactory.create(
        repository=repository,
        base_commit_sha=base_commit.commitid,
        head_commit_sha=head_commit.commitid
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(commit=base_commit, report=Report())
    head_full_commit = FullCommit(commit=head_commit, report=sample_report)
    return Comparison(
        head=head_full_commit,
        base=base_full_commit,
        pull=pull
    )
