import pytest
from redis.exceptions import LockError
from shared.reports.types import ReportTotals, SessionTotalsArray
from shared.torngit.exceptions import TorngitClientError, TorngitRepoNotFoundError

from database.models.reports import Upload
from database.tests.factories.core import (
    CommitFactory,
    ReportFactory,
    RepositoryFactory,
)
from helpers.exceptions import RepositoryWithoutValidBotError
from services.report import ReportService
from tasks.preprocess_upload import PreProcessUpload


class TestPreProcessUpload(object):
    def test_is_running(self, mock_redis):
        mock_redis.get = lambda lock_name: "value" if lock_name == "lock_1" else None
        task = PreProcessUpload()
        assert task._is_running(mock_redis, "lock_1") == True
        assert task._is_running(mock_redis, "lock_2") == False

    @pytest.mark.django_db(databases={"default"})
    def test_preprocess_task(
        self,
        mocker,
        mock_configuration,
        dbsession,
        mock_storage,
        mock_redis,
        celery_app,
        sample_report,
    ):
        # get_existing_report_for_commit gets called for the parent commit
        mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=sample_report,
        )
        mocked_fetch_yaml = mocker.patch.object(
            PreProcessUpload,
            "fetch_commit_yaml_and_possibly_store",
            return_value={
                "flag_management": {
                    "individual_flags": [
                        {
                            "name": "unit",
                            "carryforward": True,
                        }
                    ]
                }
            },
        )
        mocker.patch.object(PreProcessUpload, "_is_running", return_value=False)

        def fake_possibly_shift(report, base, head):
            return report

        mock_possibly_shift = mocker.patch.object(
            ReportService,
            "_possibly_shift_carryforward_report",
            side_effect=fake_possibly_shift,
        )
        commit, report = self.create_commit_and_report(dbsession)

        result = PreProcessUpload().run_impl(
            dbsession,
            repoid=commit.repository.repoid,
            commitid=commit.commitid,
            report_code=None,
        )
        # assert that commit.report has carried forwarded flags sessions from its parent
        assert commit.report.details.files_array == [
            {
                "filename": "file_1.go",
                "file_index": 0,
                "file_totals": ReportTotals(
                    files=0,
                    lines=8,
                    hits=5,
                    misses=3,
                    partials=0,
                    coverage="62.50000",
                    branches=0,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=10,
                    complexity_total=2,
                    diff=0,
                ),
                "session_totals": SessionTotalsArray.build_from_encoded_data(
                    [
                        ReportTotals(
                            files=0,
                            lines=8,
                            hits=5,
                            misses=3,
                            partials=0,
                            coverage="62.50000",
                            branches=0,
                            methods=0,
                            messages=0,
                            sessions=0,
                            complexity=10,
                            complexity_total=2,
                            diff=0,
                        )
                    ]
                ),
                "diff_totals": None,
            },
            {
                "filename": "file_2.py",
                "file_index": 1,
                "file_totals": ReportTotals(
                    files=0,
                    lines=2,
                    hits=1,
                    misses=0,
                    partials=1,
                    coverage="50.00000",
                    branches=1,
                    methods=0,
                    messages=0,
                    sessions=0,
                    complexity=0,
                    complexity_total=0,
                    diff=0,
                ),
                "session_totals": SessionTotalsArray.build_from_encoded_data(
                    [
                        ReportTotals(
                            files=0,
                            lines=2,
                            hits=1,
                            misses=0,
                            partials=1,
                            coverage="50.00000",
                            branches=1,
                            methods=0,
                            messages=0,
                            sessions=0,
                            complexity=0,
                            complexity_total=0,
                            diff=0,
                        )
                    ]
                ),
                "diff_totals": None,
            },
        ]
        for sess_id, session in sample_report.sessions.items():
            upload = (
                dbsession.query(Upload)
                .filter_by(report_id=commit.report.id_, order_number=sess_id)
                .first()
            )
            assert upload
            assert upload.flag_names == ["unit"]
        assert result == {
            "preprocessed_upload": True,
            "reportid": str(report.external_id),
            "updated_commit": False,
        }
        mocked_fetch_yaml.assert_called()
        mock_possibly_shift.assert_called()

    def create_commit_and_report(self, dbsession):
        repository = RepositoryFactory()
        parent_commit = CommitFactory(repository=repository)
        parent_commit_report = ReportFactory(commit=parent_commit)
        commit = CommitFactory(
            _report_json=None,
            parent_commit_id=parent_commit.commitid,
            repository=repository,
        )
        report = ReportFactory(commit=commit)
        dbsession.add(parent_commit)
        dbsession.add(parent_commit_report)
        dbsession.add(commit)
        dbsession.add(report)
        dbsession.flush()
        return commit, report

    def test_run_impl_already_running(self, dbsession, mocker, mock_redis):
        mocker.patch.object(PreProcessUpload, "_is_running", return_value=True)
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        result = PreProcessUpload().run_impl(
            dbsession,
            repoid=commit.repository.repoid,
            commitid=commit.commitid,
            report_code=None,
        )
        assert result == {"preprocessed_upload": False, "reason": "already_running"}

    def test_run_impl_unobtainable_lock(self, dbsession, mocker, mock_redis):
        mocker.patch.object(PreProcessUpload, "_is_running", return_value=False)
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        mock_redis.lock.side_effect = LockError()
        result = PreProcessUpload().run_impl(
            dbsession,
            repoid=commit.repository.repoid,
            commitid=commit.commitid,
            report_code=None,
        )
        assert result == {
            "preprocessed_upload": False,
            "reason": "unable_to_acquire_lock",
        }

    def test_get_repo_provider_service_no_bot(self, dbsession, mocker):
        mocker.patch("tasks.preprocess_upload.save_commit_error")
        mock_get_repo_service = mocker.patch(
            "tasks.preprocess_upload.get_repo_provider_service"
        )
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        commit = CommitFactory.create()
        repo_provider = PreProcessUpload().get_repo_service(commit)
        assert repo_provider is None

    def test_preprocess_upload_fail_no_provider_service(self, dbsession, mocker):
        mocker.patch("tasks.preprocess_upload.save_commit_error")
        mock_get_repo_service = mocker.patch(
            "tasks.preprocess_upload.get_repo_provider_service"
        )
        mock_get_repo_service.side_effect = RepositoryWithoutValidBotError()
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        res = PreProcessUpload().process_impl_within_lock(
            db_session=dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            report_code=None,
        )
        assert res == {
            "preprocessed_upload": False,
            "updated_commit": False,
            "error": "Failed to get repository_service",
        }
