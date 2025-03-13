# TODO: Clean this

import pytest
from shared.reports.readonly import ReadOnlyReport
from shared.reports.reportfile import ReportFile
from shared.reports.resources import Report
from shared.reports.types import ReportLine
from shared.utils.sessions import Session

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.repository import EnrichedPull


def get_small_report(flags=None):
    if flags is None:
        flags = ["integration"]
    report = Report()
    first_file = ReportFile("file_1.go")
    first_file.append(
        1, ReportLine.create(coverage=1, sessions=[[0, 1]], complexity=(11, 20))
    )
    first_file.append(3, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    first_file.append(5, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(6, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    second_file = ReportFile("file_2.py")
    second_file.append(12, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    second_file.append(51, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    report.append(first_file)
    report.append(second_file)
    report.add_session(Session(flags=flags))
    return report


@pytest.fixture
def sample_report():
    report = Report()
    first_file = ReportFile("file_1.go")
    first_file.append(
        1, ReportLine.create(coverage=1, sessions=[[0, 1]], complexity=(10, 2))
    )
    first_file.append(2, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    first_file.append(3, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(5, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(6, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    first_file.append(8, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(9, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    first_file.append(10, ReportLine.create(coverage=0, sessions=[[0, 1]]))
    second_file = ReportFile("file_2.py")
    second_file.append(12, ReportLine.create(coverage=1, sessions=[[0, 1]]))
    second_file.append(
        51, ReportLine.create(coverage="1/2", type="b", sessions=[[0, 1]])
    )
    report.append(first_file)
    report.append(second_file)
    report.add_session(Session(flags=["unit"]))
    return report


@pytest.fixture
def sample_comparison(dbsession, request, sample_report):
    repository = RepositoryFactory.create(
        owner__username=request.node.name, owner__service="github"
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository, author__service="github")
    head_commit = CommitFactory.create(
        repository=repository, branch="new_branch", author__service="github"
    )
    pull = PullFactory.create(
        repository=repository, base=base_commit.commitid, head=head_commit.commitid
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    repository = base_commit.repository
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(get_small_report())
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            project_coverage_base=base_full_commit,
            patch_coverage_base_commitid=base_commit.commitid,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecov-test-user"},
                    "base": {"branch": "master", "commitid": base_commit.commitid},
                    "head": {
                        "branch": "reason/some-testing",
                        "commitid": head_commit.commitid,
                    },
                    "number": str(pull.pullid),
                    "id": str(pull.pullid),
                    "state": "open",
                    "title": "Creating new code for reasons no one knows",
                },
            ),
        )
    )
