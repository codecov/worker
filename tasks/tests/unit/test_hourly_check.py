from tasks.hourly_check import HourlyCheckTask


class TestHourlyCheck(object):
    def test_simple_case(self, dbsession):
        task = HourlyCheckTask()
        assert task.run_cron_task(dbsession) == {"checked": True}

    def test_get_min_seconds_interval_between_executions(self, dbsession):
        assert isinstance(
            HourlyCheckTask.get_min_seconds_interval_between_executions(), int
        )
        # The specifics don't matter, but the number needs to be somewhat big
        assert HourlyCheckTask.get_min_seconds_interval_between_executions() > 600
