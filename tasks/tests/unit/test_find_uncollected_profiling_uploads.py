from datetime import datetime

import pytest

from database.tests.factories.profiling import (
    ProfilingCommitFactory,
    ProfilingUploadFactory,
)
from tasks.profiling_find_uncollected import FindUncollectedProfilingsTask


class TestFindUncollectedProfilingsTask(object):
    def test_get_min_seconds_interval_between_executions(self):
        task = FindUncollectedProfilingsTask()
        assert task.get_min_seconds_interval_between_executions() == 800

    def test_run_cron_task_empty(self, dbsession):
        task = FindUncollectedProfilingsTask()
        res = task.run_cron_task(dbsession)
        assert res == {"delayed_profiling_ids": [], "delayed_profiling_ids_count": 0}

    def test_run_cron_task_one_matching_profiling(self, dbsession, mocker):
        mocked_get_utc_now = mocker.patch(
            "tasks.profiling_find_uncollected.get_utc_now"
        )
        mocked_collection_task = mocker.patch(
            "tasks.profiling_find_uncollected.profiling_collection_task",
            delay=mocker.MagicMock(
                return_value=mocker.MagicMock(
                    as_tuple=mocker.MagicMock(return_value=("1234",))
                )
            ),
        )
        mocked_get_utc_now.return_value = datetime(2021, 7, 3, 6, 8, 12)
        pcf = ProfilingCommitFactory.create(created_at=datetime(2021, 7, 1, 6, 8, 12))
        dbsession.add(pcf)
        dbsession.flush()
        profiling_upload = ProfilingUploadFactory.create(profiling_commit=pcf)
        dbsession.add(profiling_upload)
        dbsession.flush()
        task = FindUncollectedProfilingsTask()
        res = task.run_cron_task(dbsession)
        assert res == {
            "delayed_profiling_ids": [(pcf.id, 1, ("1234",))],
            "delayed_profiling_ids_count": 1,
        }
        mocked_collection_task
