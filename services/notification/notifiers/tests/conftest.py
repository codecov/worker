import pytest
from shared.reports.readonly import ReadOnlyReport
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.utils.sessions import Session

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.archive import ArchiveService
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.report import ReportService
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
def small_report():
    return get_small_report()


@pytest.fixture
def sample_report_without_flags():
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
    report.add_session(Session(flags=None))
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
def sample_commit_with_report_already_carriedforward(dbsession, mock_storage):
    sessions_dict = {
        "0": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": [],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
        "1": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["unit"],
            "j": None,
            "n": None,
            "p": None,
            "st": "uploaded",
            "t": None,
            "u": None,
        },
        "2": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["enterprise"],
            "j": None,
            "n": None,
            "p": None,
            "st": "carriedforward",
            "t": None,
            "u": None,
            "se": {"carriedforward_from": "123456789sha"},
        },
        "3": {
            "N": None,
            "a": None,
            "c": None,
            "d": None,
            "e": None,
            "f": ["integration"],
            "j": None,
            "n": None,
            "p": None,
            "st": "carriedforward",
            "t": None,
            "u": None,
        },
    }
    file_headers = {
        "file_00.py": [
            0,
            [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 12, 0, 2, "85.71429", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_01.py": [
            1,
            [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 8, 0, 3, "72.72727", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_10.py": [
            10,
            [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 10, 6, 1, 3, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_11.py": [
            11,
            [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 23, 15, 1, 7, "65.21739", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_12.py": [
            12,
            [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 8, 0, 6, "57.14286", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_13.py": [
            13,
            [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 15, 9, 0, 6, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_14.py": [
            14,
            [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 23, 13, 0, 10, "56.52174", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_02.py": [
            2,
            [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 13, 9, 0, 4, "69.23077", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_03.py": [
            3,
            [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 16, 8, 0, 8, "50.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_04.py": [
            4,
            [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 10, 6, 0, 4, "60.00000", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_05.py": [
            5,
            [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 10, 0, 4, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_06.py": [
            6,
            [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 9, 7, 1, 1, "77.77778", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_07.py": [
            7,
            [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 9, 0, 2, "81.81818", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_08.py": [
            8,
            [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 11, 6, 0, 5, "54.54545", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
        "file_09.py": [
            9,
            [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0],
            [None, None, None, [0, 14, 10, 1, 3, "71.42857", 0, 0, 0, 0, 0, 0, 0]],
            None,
        ],
    }
    commit = CommitFactory.create(
        report_json={"sessions": sessions_dict, "files": file_headers},
        repository__owner__service="github",
    )
    dbsession.add(commit)
    dbsession.flush()
    with open("tasks/tests/samples/sample_chunks_4_sessions.txt") as f:
        content = f.read().encode()
        archive_hash = ArchiveService.get_archive_hash(commit.repository)
        chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
        mock_storage.write_file("archive", chunks_url, content)
    return commit


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
        return ComparisonProxy(
            Comparison(
                head=head_full_commit,
                base=base_full_commit,
                enriched_pull=EnrichedPull(database_pull=pull, provider_pull={}),
            )
        )

    return _comparison


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
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecov-test-user"},
                    "base": {"branch": "master", "commitid": base_commit.commitid,},
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


@pytest.fixture
def sample_comparison_coverage_carriedforward(
    dbsession, request, sample_commit_with_report_already_carriedforward
):
    head_commit = sample_commit_with_report_already_carriedforward
    base_commit = CommitFactory.create(repository=head_commit.repository)

    repository = head_commit.repository
    dbsession.add(repository)
    dbsession.flush()
    pull = PullFactory.create(
        repository=repository, base=base_commit.commitid, head=head_commit.commitid
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()

    yaml_dict = {"flags": {"enterprise": {"carryforward": True}}}
    report = ReportService(yaml_dict).build_report_from_commit(head_commit)
    report._totals = (
        None  # need to reset the report to get it to recalculate totals correctly
    )
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(report)
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(report)
    )

    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
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


@pytest.fixture
def sample_comparison_negative_change(dbsession, request, sample_report):
    repository = RepositoryFactory.create(
        owner__username=request.node.name, owner__service="github"
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
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(get_small_report())
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecov-test-user"},
                    "base": {"branch": "master", "commitid": base_commit.commitid,},
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


@pytest.fixture
def sample_comparison_no_change(dbsession, request, sample_report):
    repository = RepositoryFactory.create(
        owner__username=request.node.name, owner__service="github"
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
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecov-test-user"},
                    "base": {"branch": "master", "commitid": base_commit.commitid,},
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


@pytest.fixture
def sample_comparison_without_pull(dbsession, request, sample_report):
    repository = RepositoryFactory.create(
        owner__username=request.node.name, owner__service="github"
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(repository=repository, author__service="github")
    head_commit = CommitFactory.create(
        repository=repository, branch="new_branch", author__service="github"
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
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
            base=base_full_commit,
            enriched_pull=EnrichedPull(database_pull=None, provider_pull=None),
        )
    )


@pytest.fixture
def sample_comparison_database_pull_without_provider(dbsession, request, sample_report):
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
    base_full_commit = FullCommit(
        commit=base_commit, report=ReadOnlyReport.create_from_report(get_small_report())
    )
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(database_pull=pull, provider_pull=None),
        )
    )


def generate_sample_comparison(username, dbsession, base_report, head_report):
    repository = RepositoryFactory.create(
        owner__username=username, owner__service="github"
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
    base_full_commit = FullCommit(commit=base_commit, report=base_report)
    head_full_commit = FullCommit(commit=head_commit, report=head_report)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecov-test-user"},
                    "base": {"branch": "master", "commitid": base_commit.commitid,},
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


@pytest.fixture
def sample_comparison_without_base_report(dbsession, request, sample_report):
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
    dbsession.add(head_commit)
    dbsession.add(base_commit)
    dbsession.add(pull)
    dbsession.flush()
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    base_full_commit = FullCommit(commit=base_commit, report=None)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecov-test-user"},
                    "base": {"branch": "master", "commitid": base_commit.commitid,},
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


@pytest.fixture
def sample_comparison_matching_flags(dbsession, request, sample_report):
    return generate_sample_comparison(
        request.node.name, dbsession, get_small_report(flags=["unit"]), sample_report
    )


@pytest.fixture
def sample_comparison_without_base_with_pull(dbsession, request, sample_report):
    repository = RepositoryFactory.create(
        owner__username=request.node.name, owner__service="github"
    )
    dbsession.add(repository)
    dbsession.flush()
    head_commit = CommitFactory.create(repository=repository, branch="new_branch")
    pull = PullFactory.create(
        repository=repository, base="base_commitid", head=head_commit.commitid
    )
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    head_full_commit = FullCommit(
        commit=head_commit, report=ReadOnlyReport.create_from_report(sample_report)
    )
    base_full_commit = FullCommit(commit=None, report=None)
    return ComparisonProxy(
        Comparison(
            head=head_full_commit,
            base=base_full_commit,
            enriched_pull=EnrichedPull(
                database_pull=pull,
                provider_pull={
                    "author": {"id": "12345", "username": "codecov-test-user"},
                    "base": {
                        "branch": "master",
                        "commitid": "cdf9aa4bd2c6bcd8a662864097cb62a85a2fd55b",
                    },
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
