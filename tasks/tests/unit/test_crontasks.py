from datetime import datetime, timedelta, timezone

from redis.exceptions import LockError

from tasks.crontasks import CodecovCronTask


class SampleCronTask(CodecovCronTask):
    name = "test.SampleCronTask"

    def get_min_seconds_interval_between_executions(self):
        return 234

    @property
    def hard_time_limit_task(self):
        return 100

    def run_cron_task(self, dbsession):
        return {"unusual": "return", "value": ["something"]}


class TestCrontasks(object):
    def test_simple_run(self, dbsession, mock_redis):
        generation_time = datetime(2021, 1, 2, 0, 3, 4).replace(tzinfo=timezone.utc)
        task = SampleCronTask()
        res = task.run_impl(
            dbsession, cron_task_generation_time_iso=generation_time.isoformat()
        )
        assert res == {
            "executed": True,
            "result": {"unusual": "return", "value": ["something"]},
        }

    def test_simple_run_with_too_recent_call(self, dbsession, mock_redis):
        generation_time = datetime(2021, 1, 2, 0, 3, 4).replace(tzinfo=timezone.utc)
        mock_redis.get.return_value = (
            generation_time - timedelta(seconds=5)
        ).timestamp()
        task = SampleCronTask()
        res = task.run_impl(
            dbsession, cron_task_generation_time_iso=generation_time.isoformat()
        )
        assert res == {"executed": False}

    def test_simple_run_with_lock_error(self, dbsession, mock_redis):
        generation_time = datetime(2021, 1, 2, 0, 3, 4).replace(tzinfo=timezone.utc)
        mock_redis.lock.side_effect = LockError
        task = SampleCronTask()
        res = task.run_impl(
            dbsession, cron_task_generation_time_iso=generation_time.isoformat()
        )
        assert res == {"executed": False}
