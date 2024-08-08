import pytest
from celery.exceptions import Retry
from mock import MagicMock
from redis.exceptions import LockError
from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from database.tests.factories.core import CommitFactory
from helpers.labels import SpecialLabelsEnum
from tasks.upload_clean_labels_index import (
    CleanLabelsIndexTask,
    OwnerContext,
    ReadOnlyArgs,
    RepoContext,
    ReportService,
    UserYaml,
)
from tasks.upload_processor import UPLOAD_PROCESSING_LOCK_NAME
from test_utils.base import BaseTestCase


@pytest.fixture
def sample_report_with_labels():
    report = Report()
    # All labels are being used
    labels_index = {
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
        1: "some_test",
        2: "another_test",
    }
    report.header = {"labels_index": labels_index}
    report_file = ReportFile("file.py")
    report_file._lines = [
        ReportLine.create(1, None, [[0, 1]], None, None, [[0, 1, None, [0]]]),
        None,
        ReportLine.create(1, None, [[0, 1]], None, None, [[0, 1, None, [1, 2]]]),
        ReportLine.create(
            "1/2", None, [[0, "1/2"]], None, None, [[0, "1/2", None, [1]]]
        ),
        ReportLine.create(
            "1/2", None, [[0, "1/2"]], None, None, [[0, "1/2", None, [2]]]
        ),
    ]
    report.append(report_file)
    return report


@pytest.fixture
def sample_report_with_labels_and_renames():
    report = Report()
    labels_index = {
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
        1: "some_test",  # This label isn't being used
        2: "another_test",
        3: "some_test_renamed",
    }
    report.header = {"labels_index": labels_index}
    report_file = ReportFile("file.py")
    report_file._lines = [
        ReportLine.create(1, None, [[0, 1]], None, None, [[0, 1, None, [0]]]),
        None,
        ReportLine.create(1, None, [[0, 1]], None, None, [[0, 1, None, [2, 3]]]),
        ReportLine.create(
            "1/2", None, [[0, "1/2"]], None, None, [[0, "1/2", None, [3]]]
        ),
        ReportLine.create(
            "1/2", None, [[0, "1/2"]], None, None, [[0, "1/2", None, [2]]]
        ),
    ]
    report.append(report_file)
    return report


# Simplified version of the FakeRedis class defined in tasks/tests/unit/test_upload_task.py
class FakeRedis(object):
    """
    This is a fake, very rudimentary redis implementation to ease the managing
     of mocking `exists`, `lpop` and whatnot in the context of Upload jobs
    """

    def __init__(self, mocker):
        self.keys = {}
        self.lock = mocker.MagicMock()
        self.sismember = mocker.MagicMock()
        self.hdel = mocker.MagicMock()

    def get(self, key):
        res = None
        if self.keys.get(key) is not None:
            res = self.keys.get(key)
        if res is None:
            return None
        if not isinstance(res, (str, bytes)):
            return str(res).encode()
        if not isinstance(res, bytes):
            return res.encode()
        return res


@pytest.fixture
def mock_redis(mocker):
    m = mocker.patch("services.redis._get_redis_instance_from_url")
    redis_server = FakeRedis(mocker)
    m.return_value = redis_server
    yield redis_server


class TestCleanLabelsIndexSyncronization(object):
    @pytest.mark.parametrize(
        "commitid, is_currently_processing", [("sha_1", True), ("sha_2", False)]
    )
    def test__is_currently_processing(
        self, mock_redis, commitid, is_currently_processing
    ):
        mock_redis.keys = {"upload_processing_lock_1_sha_1": True}
        lock_name = UPLOAD_PROCESSING_LOCK_NAME(1, commitid)
        task = CleanLabelsIndexTask()
        assert (
            task._is_currently_processing(mock_redis, lock_name)
            == is_currently_processing
        )

    def test_retry_currently_processing(self, dbsession, mocker, mock_redis):
        commit = CommitFactory()
        dbsession.add(commit)
        dbsession.flush()
        mock_currently_processing = mocker.patch.object(
            CleanLabelsIndexTask, "_is_currently_processing", return_value=True
        )
        task = CleanLabelsIndexTask()
        with pytest.raises(Retry):
            task.run_impl(dbsession, commit.repository.repoid, commit.commitid)
        lock_name = UPLOAD_PROCESSING_LOCK_NAME(
            commit.repository.repoid, commit.commitid
        )
        mock_currently_processing.assert_called_with(mock_redis, lock_name)

    def test_retry_failed_to_get_lock(self, dbsession, mocker, mock_redis):
        commit = CommitFactory()
        dbsession.add(commit)
        dbsession.flush()
        mock_currently_processing = mocker.patch.object(
            CleanLabelsIndexTask, "_is_currently_processing", return_value=False
        )
        mock_run_impl_within_lock = mocker.patch.object(
            CleanLabelsIndexTask, "run_impl_within_lock"
        )
        # Mock the getters of read_only_args
        mocker.patch.object(
            CleanLabelsIndexTask, "_get_best_effort_commit_yaml", return_value={}
        )
        mock_redis.lock.side_effect = LockError
        task = CleanLabelsIndexTask()
        with pytest.raises(Retry):
            task.run_impl(dbsession, commit.repository.repoid, commit.commitid)
        mock_currently_processing.assert_called()
        mock_run_impl_within_lock.assert_not_called()

    def test_call_actual_logic(self, dbsession, mocker, mock_redis):
        commit = CommitFactory()
        dbsession.add(commit)
        dbsession.flush()
        mock_currently_processing = mocker.patch.object(
            CleanLabelsIndexTask, "_is_currently_processing", return_value=False
        )
        mock_run_impl_within_lock = mocker.patch.object(
            CleanLabelsIndexTask, "run_impl_within_lock", return_value="return_value"
        )
        mocker.patch.object(
            CleanLabelsIndexTask, "_get_best_effort_commit_yaml", return_value={}
        )
        task = CleanLabelsIndexTask()
        task.run_impl(
            dbsession, commit.repository.repoid, commit.commitid, report_code="code"
        )
        mock_currently_processing.assert_called()
        mock_run_impl_within_lock.assert_called_with(
            dbsession,
            ReadOnlyArgs(commit=commit, commit_yaml={}, report_code="code"),
        )


class TestCleanLabelsIndexReadOnlyArgs(object):
    def test__get_commit_or_fail_success(self, dbsession):
        commit = CommitFactory()
        dbsession.add(commit)
        dbsession.flush()
        task = CleanLabelsIndexTask()
        assert (
            task._get_commit_or_fail(
                dbsession, commit.repository.repoid, commit.commitid
            )
            == commit
        )

    def test__get_commit_or_fail_fail(self, dbsession):
        task = CleanLabelsIndexTask()
        with pytest.raises(AssertionError) as exp:
            task._get_commit_or_fail(dbsession, 10000, "commit_that_dont_exist")
        assert str(exp.value) == "Commit not found in database."

    def test__get_best_effort_commit_yaml_from_provider(self, dbsession, mocker):
        commit = CommitFactory()
        dbsession.add(commit)
        mock_repo_service = MagicMock(name="repo_provider_service")
        mock_fetch_commit = mocker.patch(
            "tasks.upload_clean_labels_index.fetch_commit_yaml_from_provider",
            return_value={
                "yaml_for": f"commit_{commit.commitid}",
                "origin": "git_provider",
            },
        )
        task = CleanLabelsIndexTask()
        res = task._get_best_effort_commit_yaml(commit, mock_repo_service)
        assert res == {
            "yaml_for": f"commit_{commit.commitid}",
            "origin": "git_provider",
        }
        mock_fetch_commit.assert_called_with(commit, mock_repo_service)

    def test__get_best_effort_commit_yaml_from_db(self, dbsession, mocker):
        commit = CommitFactory()
        dbsession.add(commit)
        mock_fetch_commit = mocker.patch(
            "tasks.upload_clean_labels_index.fetch_commit_yaml_from_provider"
        )
        mock_final_yaml = mocker.patch.object(
            UserYaml,
            "get_final_yaml",
            return_value=UserYaml.from_dict(
                {"yaml_for": f"commit_{commit.commitid}", "origin": "database"}
            ),
        )
        task = CleanLabelsIndexTask()
        res = task._get_best_effort_commit_yaml(commit, None)
        assert res == {"yaml_for": f"commit_{commit.commitid}", "origin": "database"}
        owner = commit.repository.owner
        mock_fetch_commit.assert_not_called()
        mock_final_yaml.assert_called_with(
            owner_yaml=commit.repository.owner.yaml,
            repo_yaml=commit.repository.yaml,
            commit_yaml=None,
            owner_context=OwnerContext(
                ownerid=owner.ownerid,
                owner_plan=owner.plan,
                owner_onboarding_date=owner.createstamp,
            ),
            repo_context=RepoContext(repo_creation_date=commit.repository.created_at),
        )


class TestCleanLabelsIndexLogic(BaseTestCase):
    def test_clean_labels_report_not_found(self, dbsession, mocker):
        commit = CommitFactory()
        dbsession.add(commit)
        mock_get_report = mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=None
        )
        task = CleanLabelsIndexTask()
        read_only_args = ReadOnlyArgs(commit=commit, report_code=None, commit_yaml={})
        res = task.run_impl_within_lock(read_only_args)
        assert res == {"success": False, "error": "Report not found"}
        mock_get_report.assert_called_with(commit, report_code=None)

    def test_clean_labels_no_labels_index_in_report(self, dbsession, mocker):
        commit = CommitFactory()
        dbsession.add(commit)
        report = Report()
        assert report.header == {}
        mock_get_report = mocker.patch.object(
            ReportService, "get_existing_report_for_commit", return_value=report
        )
        task = CleanLabelsIndexTask()
        read_only_args = ReadOnlyArgs(commit=commit, report_code=None, commit_yaml={})
        res = task.run_impl_within_lock(read_only_args)
        assert res == {
            "success": False,
            "error": "Labels index is empty, nothing to do",
        }
        mock_get_report.assert_called_with(commit, report_code=None)

    def test_clean_labels_no_change_needed(
        self, dbsession, mocker, sample_report_with_labels
    ):
        commit = CommitFactory()
        dbsession.add(commit)
        mock_get_report = mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=sample_report_with_labels,
        )
        mock_save_report = mocker.patch.object(
            ReportService, "save_report", return_value={"url": "the_storage_path"}
        )
        task = CleanLabelsIndexTask()
        read_only_args = ReadOnlyArgs(commit=commit, report_code=None, commit_yaml={})
        sample_report_better_read_original = self.convert_report_to_better_readable(
            sample_report_with_labels
        )
        res = task.run_impl_within_lock(read_only_args)
        assert res == {"success": True}
        mock_get_report.assert_called_with(commit, report_code=None)
        mock_save_report.assert_called()
        assert sample_report_with_labels.labels_index == {
            SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "some_test",
            2: "another_test",
        }
        assert (
            self.convert_report_to_better_readable(sample_report_with_labels)
            == sample_report_better_read_original
        )

    def test_clean_labels_with_renames(
        self, dbsession, mocker, sample_report_with_labels_and_renames
    ):
        commit = CommitFactory()
        dbsession.add(commit)
        mock_get_report = mocker.patch.object(
            ReportService,
            "get_existing_report_for_commit",
            return_value=sample_report_with_labels_and_renames,
        )
        mock_save_report = mocker.patch.object(
            ReportService, "save_report", return_value={"url": "the_storage_path"}
        )
        task = CleanLabelsIndexTask()
        read_only_args = ReadOnlyArgs(commit=commit, report_code=None, commit_yaml={})
        res = task.run_impl_within_lock(read_only_args)
        assert res == {"success": True}
        mock_get_report.assert_called_with(commit, report_code=None)
        mock_save_report.assert_called()
        assert sample_report_with_labels_and_renames.labels_index == {
            SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "another_test",
            2: "some_test_renamed",
        }
        readable_report = self.convert_report_to_better_readable(
            sample_report_with_labels_and_renames
        )["archive"]
        print(readable_report)
        assert readable_report == {
            "file.py": [
                (
                    1,
                    1,
                    None,
                    [[0, 1, None, None, None]],
                    None,
                    None,
                    [(0, 1, None, [0])],
                ),
                (
                    3,
                    1,
                    None,
                    [[0, 1, None, None, None]],
                    None,
                    None,
                    [(0, 1, None, [1, 2])],
                ),
                (
                    4,
                    "1/2",
                    None,
                    [[0, "1/2", None, None, None]],
                    None,
                    None,
                    [(0, "1/2", None, [2])],
                ),
                (
                    5,
                    "1/2",
                    None,
                    [[0, "1/2", None, None, None]],
                    None,
                    None,
                    [(0, "1/2", None, [1])],
                ),
            ]
        }
