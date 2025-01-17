import pytest
from redis.exceptions import LockError
from shared.config import ConfigHelper
from shared.django_apps.core.tests.factories import CommitFactory, RepositoryFactory
from shared.django_apps.reports.models import CommitReport
from shared.django_apps.reports.tests.factories import UploadFactory

from tasks.ta_process_flakes import TAProcessFlakesTask


@pytest.fixture
def mock_repo():
    return RepositoryFactory()


@pytest.fixture
def mock_redis(mocker):
    m = mocker.patch("services.redis._get_redis_instance_from_url")
    redis_server = mocker.MagicMock()
    m.return_value = redis_server
    yield redis_server


@pytest.fixture
def mock_config(mock_configuration):
    mock_config = ConfigHelper()
    mock_config.set_params(
        mock_configuration._params
        | {
            "setup": {"test_analytics_database": {"enabled": True}},
            "services": {
                "bigquery": {
                    "write_enabled": True,
                    "read_enabled": True,
                }
            },
        }
    )
    return mock_config


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_process_flakes_disabled_by_config(
    mocker, mock_repo, mock_configuration, mock_redis
):
    mock_config = ConfigHelper()
    mock_config.set_params(
        mock_configuration._params
        | {"setup": {"test_analytics_database": {"enabled": False}}}
    )
    mocker.patch("django_scaffold.settings.get_config", return_value=mock_config)

    mock_driver = mocker.Mock()
    mock_driver_cls = mocker.patch(
        "tasks.ta_process_flakes.BQDriver", return_value=mock_driver
    )

    mock_redis.get.side_effect = ["1", None]

    commit = CommitFactory(repository=mock_repo)
    result = TAProcessFlakesTask().run_impl(
        _db_session=None,
        repo_id=mock_repo.repoid,
        commit_id=commit.commitid,
    )

    assert result == {"successful": True}
    mock_driver_cls.assert_not_called()
    mock_driver.write_flakes.assert_not_called()


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_process_flakes_disabled_by_settings(
    mocker, mock_repo, mock_config, mock_redis
):
    # Mock settings to disable BigQuery write
    mocker.patch("tasks.ta_process_flakes.settings.BIGQUERY_WRITE_ENABLED", False)

    mock_driver = mocker.Mock()
    mock_driver_cls = mocker.patch(
        "tasks.ta_process_flakes.BQDriver", return_value=mock_driver
    )

    mock_redis.get.side_effect = ["1", None]

    commit = CommitFactory(repository=mock_repo)
    result = TAProcessFlakesTask().run_impl(
        _db_session=None,
        repo_id=mock_repo.repoid,
        commit_id=commit.commitid,
    )

    assert result == {"successful": True}
    mock_driver_cls.assert_not_called()
    mock_driver.write_flakes.assert_not_called()


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_process_flakes_no_uploads(mocker, mock_repo, mock_config, mock_redis):
    # Mock settings to enable BigQuery write
    mocker.patch("tasks.ta_process_flakes.settings.BIGQUERY_WRITE_ENABLED", True)

    mock_driver = mocker.Mock()
    mock_driver_cls = mocker.patch(
        "tasks.ta_process_flakes.BQDriver", return_value=mock_driver
    )

    mock_redis.get.side_effect = ["1", None]

    commit = CommitFactory(repository=mock_repo)
    result = TAProcessFlakesTask().run_impl(
        _db_session=None,
        repo_id=mock_repo.repoid,
        commit_id=commit.commitid,
    )

    assert result == {"successful": True}
    mock_driver_cls.assert_not_called()
    mock_driver.write_flakes.assert_not_called()


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_process_flakes_with_uploads(mocker, mock_repo, mock_config, mock_redis):
    # Mock settings to enable BigQuery write
    mocker.patch("tasks.ta_process_flakes.settings.BIGQUERY_WRITE_ENABLED", True)

    mock_driver = mocker.Mock()
    mock_driver_cls = mocker.patch(
        "tasks.ta_process_flakes.BQDriver", return_value=mock_driver
    )

    # Configure redis.get to return value first then None
    mock_redis.get.side_effect = ["1", None]

    commit = CommitFactory(repository=mock_repo)

    # Create multiple uploads with different states
    upload1 = UploadFactory(
        report__report_type=CommitReport.ReportType.TEST_RESULTS.value,
        report__commit=commit,
        state="v2_finished",
    )
    upload2 = UploadFactory(
        report__report_type=CommitReport.ReportType.TEST_RESULTS.value,
        report__commit=commit,
        state="v2_finished",
    )
    # Upload that should be ignored due to state
    UploadFactory(
        report__report_type=CommitReport.ReportType.TEST_RESULTS.value,
        report__commit=commit,
        state="processing",
    )
    # Upload that should be ignored due to report type
    UploadFactory(
        report__report_type=CommitReport.ReportType.COVERAGE.value,
        report__commit=commit,
        state="v2_finished",
    )

    result = TAProcessFlakesTask().run_impl(
        _db_session=None,
        repo_id=mock_repo.repoid,
        commit_id=commit.commitid,
    )

    assert result == {"successful": True}
    mock_driver_cls.assert_called_once_with(mock_repo.repoid)
    mock_driver.write_flakes.assert_called_once()
    # Verify the uploads passed to write_flakes
    uploads_processed = mock_driver.write_flakes.call_args[0][0]
    assert len(uploads_processed) == 2
    assert set(u.id for u in uploads_processed) == {upload1.id, upload2.id}
    # Verify redis.get was called twice
    assert mock_redis.get.call_count == 2


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_process_flakes_lock_contention(mocker, mock_repo, mock_config, mock_redis):
    # Mock settings to enable BigQuery write
    mocker.patch("tasks.ta_process_flakes.settings.BIGQUERY_WRITE_ENABLED", True)

    mock_driver = mocker.Mock()
    mocker.patch("tasks.ta_process_flakes.BQDriver", return_value=mock_driver)

    mock_redis.lock = mocker.Mock(side_effect=LockError("Lock already acquired"))

    commit = CommitFactory(repository=mock_repo)
    result = TAProcessFlakesTask().run_impl(
        _db_session=None,
        repo_id=mock_repo.repoid,
        commit_id=commit.commitid,
    )

    assert result == {"successful": False}
    mock_driver.write_flakes.assert_not_called()
