import pytest
from redis.exceptions import LockError
from shared.django_apps.core.tests.factories import RepositoryFactory
from shared.django_apps.test_analytics.models import LastRollupDate

from tasks.ta_cache_analytics import TACacheAnalyticsTask


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
    mock_configuration.set_params(
        mock_configuration._params
        | {
            "services": {
                "test_analytics": {"write_buckets": ["test-bucket"]},
                "bigquery": {"write_enabled": True},
            }
        }
    )
    return mock_configuration


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_cache_analytics_disabled_by_settings(
    mocker, mock_repo, mock_config, mock_redis
):
    # Mock settings to disable BigQuery write
    mocker.patch("tasks.ta_cache_analytics.settings.BIGQUERY_WRITE_ENABLED", False)

    mock_bq_driver = mocker.Mock()
    mock_pg_driver = mocker.Mock()
    mocker.patch("tasks.ta_cache_analytics.BQDriver", return_value=mock_bq_driver)
    mocker.patch("tasks.ta_cache_analytics.PGDriver", return_value=mock_pg_driver)

    mock_redis.lock.return_value.__enter__ = lambda x: None
    mock_redis.lock.return_value.__exit__ = lambda x, y, z, a: None

    result = TACacheAnalyticsTask().run_impl(
        db_session=None,  # type: ignore[arg-type]
        repoid=mock_repo.repoid,
        branch="main",
    )

    assert result == {"success": True}
    mock_bq_driver.cache_analytics.assert_not_called()
    mock_pg_driver.cache_analytics.assert_has_calls(
        [mocker.call(["test-bucket"], "main"), mocker.call(["test-bucket"], None)]
    )


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_cache_analytics_with_bigquery_enabled(
    mocker, mock_repo, mock_config, mock_redis
):
    mocker.patch("tasks.ta_cache_analytics.settings.BIGQUERY_WRITE_ENABLED", True)

    mock_bq_driver = mocker.Mock()
    mock_pg_driver = mocker.Mock()
    mocker.patch("tasks.ta_cache_analytics.BQDriver", return_value=mock_bq_driver)
    mocker.patch("tasks.ta_cache_analytics.PGDriver", return_value=mock_pg_driver)

    mock_redis.lock.return_value.__enter__ = lambda x: None
    mock_redis.lock.return_value.__exit__ = lambda x, y, z, a: None

    result = TACacheAnalyticsTask().run_impl(
        db_session=None,  # type: ignore[arg-type]
        repoid=mock_repo.repoid,
        branch="main",
    )

    assert result == {"success": True}
    mock_bq_driver.cache_analytics.assert_has_calls(
        [mocker.call(["test-bucket"], "main"), mocker.call(["test-bucket"], None)]
    )
    mock_pg_driver.cache_analytics.assert_has_calls(
        [mocker.call(["test-bucket"], "main"), mocker.call(["test-bucket"], None)]
    )


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_cache_analytics_lock_contention(mocker, mock_repo, mock_config, mock_redis):
    mock_redis.lock.side_effect = LockError("Lock already acquired")

    mock_bq_driver = mocker.Mock()
    mock_pg_driver = mocker.Mock()
    mocker.patch("tasks.ta_cache_analytics.BQDriver", return_value=mock_bq_driver)
    mocker.patch("tasks.ta_cache_analytics.PGDriver", return_value=mock_pg_driver)

    result = TACacheAnalyticsTask().run_impl(
        db_session=None,  # type: ignore[arg-type]
        repoid=mock_repo.repoid,
        branch="main",
    )

    assert result == {"in_progress": True}
    mock_bq_driver.cache_analytics.assert_not_called()
    mock_pg_driver.cache_analytics.assert_not_called()


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_cache_analytics_updates_last_rollup_date(
    mocker, mock_repo, mock_config, mock_redis
):
    mocker.patch("tasks.ta_cache_analytics.settings.BIGQUERY_WRITE_ENABLED", True)

    mock_bq_driver = mocker.Mock()
    mock_pg_driver = mocker.Mock()
    mocker.patch("tasks.ta_cache_analytics.BQDriver", return_value=mock_bq_driver)
    mocker.patch("tasks.ta_cache_analytics.PGDriver", return_value=mock_pg_driver)

    mock_redis.lock.return_value.__enter__ = lambda x: None
    mock_redis.lock.return_value.__exit__ = lambda x, y, z, a: None

    result = TACacheAnalyticsTask().run_impl(
        db_session=None,  # type: ignore[arg-type]
        repoid=mock_repo.repoid,
        branch="main",
    )

    assert result == {"success": True}

    # Verify LastRollupDate was updated for both branch and repo-level
    branch_rollup = LastRollupDate.objects.get(repoid=mock_repo.repoid, branch="main")
    assert branch_rollup is not None

    repo_rollup = LastRollupDate.objects.get(repoid=mock_repo.repoid, branch=None)
    assert repo_rollup is not None


@pytest.mark.django_db(transaction=True, databases={"default", "test_analytics"})
def test_ta_cache_analytics_with_custom_buckets(
    mocker, mock_repo, mock_redis, mock_config
):
    mock_config.set_params(
        mock_config._params
        | {
            "services": {
                "test_analytics": {"write_buckets": ["bucket1", "bucket2"]},
                "bigquery": {"write_enabled": True},
            }
        }
    )
    mocker.patch("tasks.ta_cache_analytics.settings.BIGQUERY_WRITE_ENABLED", True)

    mock_bq_driver = mocker.Mock()
    mock_pg_driver = mocker.Mock()
    mocker.patch("tasks.ta_cache_analytics.BQDriver", return_value=mock_bq_driver)
    mocker.patch("tasks.ta_cache_analytics.PGDriver", return_value=mock_pg_driver)

    mock_redis.lock.return_value.__enter__ = lambda x: None
    mock_redis.lock.return_value.__exit__ = lambda x, y, z, a: None

    result = TACacheAnalyticsTask().run_impl(
        db_session=None,  # type: ignore[arg-type]
        repoid=mock_repo.repoid,
        branch="main",
    )

    assert result == {"success": True}
    mock_bq_driver.cache_analytics.assert_has_calls(
        [
            mocker.call(["bucket1", "bucket2"], "main"),
            mocker.call(["bucket1", "bucket2"], None),
        ]
    )
    mock_pg_driver.cache_analytics.assert_has_calls(
        [
            mocker.call(["bucket1", "bucket2"], "main"),
            mocker.call(["bucket1", "bucket2"], None),
        ]
    )
