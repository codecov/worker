from unittest.mock import MagicMock

from tasks.health_check import HealthCheckTask


class TestHealthCheckTask(object):
    def test_get_queue_names_default(self, mock_configuration):
        health_check_task = HealthCheckTask()
        queue_names = health_check_task._get_all_queue_names_from_config()
        assert queue_names == set(["celery", "enterprise_celery"])

    def test_get_queue_names_some_config(self, mock_configuration):
        mock_configuration.set_params(
            {
                "setup": {
                    "debug": True,
                    "tasks": {
                        "celery": {"default_queue": "custom_celery"},
                        "notify": {"queue": "notify_queue"},
                        "pulls": {"queue": "pulls_queue"},
                        "synchronize": {"queue": "synchronize_queue"},
                        "flush_repo": {"queue": "flush_repo_queue"},
                        "comment": {},
                    },
                }
            }
        )
        health_check_task = HealthCheckTask()
        queue_names = health_check_task._get_all_queue_names_from_config()
        assert queue_names == set(
            [
                "custom_celery",
                "enterprise_custom_celery",
                "notify_queue",
                "enterprise_notify_queue",
                "pulls_queue",
                "enterprise_pulls_queue",
                "synchronize_queue",
                "enterprise_synchronize_queue",
                "flush_repo_queue",
                "enterprise_flush_repo_queue",
            ]
        )

    def test_get_redis_config_celery_broker(self, mocker, mock_configuration):
        mock_redis_instance_from_url = mocker.patch(
            "tasks.health_check.redis_service._get_redis_instance_from_url"
        )
        mock_redis_connection = mocker.patch(
            "tasks.health_check.redis_service.get_redis_connection"
        )
        mock_configuration.set_params(
            {"services": {"celery_broker": "redis://redis-celery-broker"}}
        )
        health_check_task = HealthCheckTask()
        health_check_task._get_correct_redis_connection()  # should come from services.celery_broker
        mock_redis_instance_from_url.assert_called_with("redis://redis-celery-broker")
        mock_redis_connection.assert_not_called()

    def test_get_redis_no_celery_broker(self, mocker, mock_configuration):
        mock_redis_instance_from_url = mocker.patch(
            "tasks.health_check.redis_service._get_redis_instance_from_url"
        )
        mock_redis_connection = mocker.patch(
            "tasks.health_check.redis_service.get_redis_connection"
        )
        mock_configuration.set_params(
            {"services": {"redis_url": "redis://redis-celery-broker"}}
        )
        health_check_task = HealthCheckTask()
        health_check_task._get_correct_redis_connection()
        mock_redis_instance_from_url.assert_not_called()
        mock_redis_connection.assert_called()

    def test_run_impl(self, mocker, mock_redis, dbsession):
        mock_metrics = mocker.patch("tasks.health_check.metrics.gauge")
        mock_redis.llen.return_value = 10
        mock_redis.return_value = MagicMock()
        health_check_task = HealthCheckTask()
        health_check_task.run_cron_task(dbsession)
        mock_metrics.assert_any_call("celery.queue.celery.len", 10)
        mock_metrics.assert_any_call("celery.queue.enterprise_celery.len", 10)

    def test_run_impl_with_configs(
        self, mocker, mock_redis, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "setup": {
                    "debug": True,
                    "tasks": {
                        "celery": {"default_queue": "custom_celery"},
                        "notify": {"queue": "notify_queue"},
                        "pulls": {"queue": "pulls_queue"},
                        "synchronize": {"queue": "synchronize_queue"},
                        "flush_repo": {"queue": "flush_repo_queue"},
                        "comment": {},
                    },
                }
            }
        )
        mock_metrics = mocker.patch("tasks.health_check.metrics.gauge")
        mock_redis.llen.return_value = 10
        mock_redis.return_value = MagicMock()
        health_check_task = HealthCheckTask()
        health_check_task.run_cron_task(dbsession)
        mock_metrics.assert_any_call("celery.queue.custom_celery.len", 10)
        mock_metrics.assert_any_call("celery.queue.notify_queue.len", 10)
        mock_metrics.assert_any_call("celery.queue.pulls_queue.len", 10)
        mock_metrics.assert_any_call("celery.queue.synchronize_queue.len", 10)
        mock_metrics.assert_any_call("celery.queue.flush_repo_queue.len", 10)

    def test_get_min_seconds_interval_between_executions(self, dbsession):
        assert isinstance(
            HealthCheckTask.get_min_seconds_interval_between_executions(), int
        )
        assert HealthCheckTask.get_min_seconds_interval_between_executions() < 10
