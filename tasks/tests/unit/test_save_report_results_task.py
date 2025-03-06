import pytest
from shared.reports.resources import Report

from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from database.tests.factories.core import ReportFactory, ReportResultsFactory
from helpers.exceptions import RepositoryWithoutValidBotError
from services.notification.notifiers.status.patch import PatchStatusNotifier
from services.report import ReportService
from services.repository import EnrichedPull
from tasks.save_report_results import SaveReportResultsTask


@pytest.fixture
def enriched_pull(dbsession, request):
    repository = RepositoryFactory.create(
        owner__username="codecov",
        owner__service="github",
        owner__unencrypted_oauth_token="testtlxuu2kfef3km1fbecdlmnb2nvpikvmoadi3",
        owner__plan="users-pr-inappm",
        name="example-python",
        image_token="abcdefghij",
        private=True,
    )
    dbsession.add(repository)
    dbsession.flush()
    base_commit = CommitFactory.create(
        repository=repository,
        author__username=f"base{request.node.name[-20:]}",
        author__service="github",
    )
    head_commit = CommitFactory.create(
        repository=repository,
        author__username=f"head{request.node.name[-20:]}",
        author__service="github",
    )
    pull = PullFactory.create(
        author__service="github",
        repository=repository,
        base=base_commit.commitid,
        head=head_commit.commitid,
        state="merged",
    )
    dbsession.add(base_commit)
    dbsession.add(head_commit)
    dbsession.add(pull)
    dbsession.flush()
    provider_pull = {
        "author": {"id": "7123", "username": "tomcat"},
        "base": {
            "branch": "master",
            "commitid": "b92edba44fdd29fcc506317cc3ddeae1a723dd08",
        },
        "head": {
            "branch": "reason/some-testing",
            "commitid": "a06aef4356ca35b34c5486269585288489e578db",
        },
        "number": "1",
        "id": "1",
        "state": "open",
        "title": "Creating new code for reasons no one knows",
    }
    return EnrichedPull(database_pull=pull, provider_pull=provider_pull)


class TestSaveReportResultsTaskHelpers(object):
    def test_fetch_parent(self, dbsession):
        task = SaveReportResultsTask()
        owner = OwnerFactory.create(
            unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            username="ThiagoCodecov",
        )
        repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
        )
        different_repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
        )
        dbsession.add(repository)
        right_parent_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=repository,
        )
        wrong_parent_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=different_repository,
        )
        another_wrong_parent_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="bf303450570d7a84f8c3cdedac5ac23e27a64c19",
            repository=repository,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            parent_commit_id="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=repository,
        )
        dbsession.add(commit)
        dbsession.add(another_wrong_parent_commit)
        dbsession.add(repository)
        dbsession.add(different_repository)
        dbsession.add(right_parent_commit)
        dbsession.add(wrong_parent_commit)
        dbsession.flush()
        assert task.fetch_parent(commit) == right_parent_commit

    def test_fetch_report(self, dbsession):
        task = SaveReportResultsTask()
        owner = OwnerFactory.create(
            unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            username="ThiagoCodecov",
        )
        repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
        )
        different_repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
        )
        dbsession.add(repository)
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository=repository,
        )
        different_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository=different_repository,
        )
        # two reports with the same commit-sha and code, but different repos
        report = ReportFactory.create(commit=commit, code="report1")
        another_report = ReportFactory.create(commit=different_commit, code="report1")
        dbsession.add(commit)
        dbsession.add(repository)
        dbsession.add(different_repository)
        dbsession.add(different_commit)
        dbsession.add(report)
        dbsession.add(another_report)
        dbsession.flush()
        assert task.fetch_report(commit, "report1") == report

    def test_fetch_commit(self, dbsession):
        task = SaveReportResultsTask()
        owner = OwnerFactory.create(
            unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            username="ThiagoCodecov",
        )
        repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
        )
        different_repository = RepositoryFactory.create(
            owner=owner, yaml={"codecov": {"max_report_age": "1y ago"}}
        )
        dbsession.add(repository)
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository=repository,
        )
        different_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository=different_repository,
        )
        dbsession.add(commit)
        dbsession.add(repository)
        dbsession.add(different_repository)
        dbsession.add(different_commit)
        dbsession.flush()
        assert (
            task.fetch_commit(dbsession, repository.repoid, commit.commitid) == commit
        )

    def test_fetch_base_commit(self, dbsession, enriched_pull):
        task = SaveReportResultsTask()
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            parent_commit_id="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
        )
        task.fetch_base_commit(
            commit, enriched_pull
        ) == enriched_pull.database_pull.base

    def test_fetch_base_and_head_reports(self, dbsession, enriched_pull, mocker):
        mocked_reports = mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=Report()
        )
        task = SaveReportResultsTask()
        base_report, head_report = task.fetch_base_and_head_reports(
            {},
            enriched_pull.database_pull.head,
            enriched_pull.database_pull.base,
            "report_code",
        )
        mocked_reports.assert_called()
        assert base_report is not None
        assert head_report is not None

    def test_fetch_yaml_dict(self, dbsession, mocker, mock_repo_provider):
        task = SaveReportResultsTask()
        mocked_fetch_yaml = mocker.patch("tasks.save_report_results.get_current_yaml")
        mocked_fetch_yaml.return_value = {"coverage": {"status": {"patch": True}}}
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        dbsession.add(commit)
        dbsession.flush()
        yaml = task.fetch_yaml_dict(None, commit, mock_repo_provider)
        mocked_fetch_yaml.assert_called_with(commit, mock_repo_provider)
        assert yaml == {"coverage": {"status": {"patch": True}}}

    def test_save_report_results_into_db(self, dbsession):
        report = ReportFactory.create()
        report_results = ReportResultsFactory.create(report=report)
        dbsession.add(report)
        dbsession.add(report_results)
        dbsession.flush()
        result = {
            "state": "completed",
            "message": "Coverage not affected when comparing aba5300...014b924",
        }
        task = SaveReportResultsTask()
        task.save_results_into_db(result, report)
        assert report_results
        assert report_results.result == result


class TestSaveReportResultsTask(object):
    def test_save_patch_results_successful(self, dbsession, mocker):
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        report = ReportFactory.create(commit=commit, code="report1")
        report_results = ReportResultsFactory.create(report=report)
        dbsession.add(report)
        dbsession.add(report_results)
        dbsession.add(commit)
        dbsession.flush()

        mocked_fetch_pull = mocker.patch(
            "tasks.save_report_results.fetch_and_update_pull_request_information_from_commit"
        )
        mocker.patch.object(
            PatchStatusNotifier,
            "build_payload",
            return_value={"state": "success", "message": "somemessage"},
        )
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=Report()
        )
        mocked_fetch_pull.return_value = None
        task = SaveReportResultsTask()
        result = task.run_impl(
            dbsession,
            repoid=commit.repository.repoid,
            commitid=commit.commitid,
            report_code="report1",
            current_yaml={},
        )
        assert result == {"report_results_saved": True, "reason": "success"}

    def test_save_patch_results_no_valid_bot(self, dbsession, mocker):
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        report = ReportFactory.create(commit=commit, code="report1")
        dbsession.add(report)
        dbsession.add(commit)
        dbsession.flush()

        mocked_fetch_pull = mocker.patch(
            "tasks.save_report_results.fetch_and_update_pull_request_information_from_commit"
        )
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=Report()
        )
        mocked_fetch_pull.return_value = None
        mock_get_repo_service = mocker.patch(
            "tasks.save_report_results.get_repo_provider_service"
        )
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        task = SaveReportResultsTask()
        result = task.run_impl(
            dbsession,
            repoid=commit.repository.repoid,
            commitid=commit.commitid,
            report_code="report1",
            current_yaml={},
        )
        assert result == {
            "report_results_saved": False,
            "reason": "repository without valid bot",
        }

    def test_save_patch_results_no_head_report(self, dbsession, mocker):
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
        )
        report = ReportFactory.create(commit=commit, code="report1")
        dbsession.add(report)
        dbsession.add(commit)
        dbsession.flush()
        mocked_fetch_pull = mocker.patch(
            "tasks.save_report_results.fetch_and_update_pull_request_information_from_commit"
        )
        mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=None
        )
        mocked_fetch_pull.return_value = None
        task = SaveReportResultsTask()
        result = task.run_impl(
            dbsession,
            repoid=commit.repository.repoid,
            commitid=commit.commitid,
            report_code="report1",
            current_yaml={},
        )
        assert result == {
            "report_results_saved": False,
            "reason": "No head report found.",
        }
