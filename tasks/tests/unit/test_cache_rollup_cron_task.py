import datetime as dt

from shared.django_apps.reports.models import LastCacheRollupDate
from shared.django_apps.reports.tests.factories import LastCacheRollupDateFactory

from tasks.cache_rollup_cron_task import CacheRollupTask
from tasks.cache_test_rollups import cache_test_rollups_task_name


def test_cache_rollup_cron_task(mock_storage, transactional_db, mocker):
    mocked_app = mocker.patch.object(
        CacheRollupTask,
        "app",
        tasks={
            cache_test_rollups_task_name: mocker.MagicMock(),
        },
    )
    rollup_date = LastCacheRollupDateFactory(
        last_rollup_date=dt.date.today() - dt.timedelta(days=1),
    )
    rollup_date.save()

    CacheRollupTask().run_cron_task(
        _db_session=None,
    )

    mocked_app.tasks[cache_test_rollups_task_name].s.assert_called_once_with(
        repoid=rollup_date.repository_id,
        branch=rollup_date.branch,
        update_date=False,
    )


def test_cache_rollup_cron_task_delete(mock_storage, transactional_db, mocker):
    mocked_app = mocker.patch.object(
        CacheRollupTask,
        "app",
        tasks={
            cache_test_rollups_task_name: mocker.MagicMock(),
        },
    )
    rollup_date = LastCacheRollupDateFactory(
        last_rollup_date=dt.date.today() - dt.timedelta(days=31),
    )

    CacheRollupTask().run_cron_task(
        _db_session=None,
    )

    mocked_app.tasks[cache_test_rollups_task_name].s.assert_not_called()

    assert LastCacheRollupDate.objects.filter(id=rollup_date.id).first() is None
