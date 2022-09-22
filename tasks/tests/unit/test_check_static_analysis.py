import pytest
from shared.staticanalysis import StaticAnalysisSingleFileSnapshotState

from database.tests.factories.staticanalysis import (
    StaticAnalysisSuiteFactory,
    StaticAnalysisSuiteFilepathFactory,
)
from tasks.static_analysis_suite_check import StaticAnalysisSuiteCheckTask


class TestStaticAnalysisCheckTask(object):
    @pytest.mark.asyncio
    async def test_simple_call_no_object_saved(self, dbsession):
        task = StaticAnalysisSuiteCheckTask()
        res = await task.run_async(dbsession, suite_id=987654321 * 7)
        assert res == {"changed_count": None, "successful": False}

    @pytest.mark.asyncio
    async def test_simple_call_with_suite_all_created(self, dbsession):
        obj = StaticAnalysisSuiteFactory.create()
        dbsession.add(obj)
        dbsession.flush()
        task = StaticAnalysisSuiteCheckTask()
        for i in range(8):
            fp_obj = StaticAnalysisSuiteFilepathFactory.create(
                analysis_suite=obj,
                file_snapshot__state_id=StaticAnalysisSingleFileSnapshotState.CREATED.db_id,
            )
            dbsession.add(fp_obj)
        dbsession.flush()
        res = await task.run_async(dbsession, suite_id=obj.id_)
        assert res == {"changed_count": 8, "successful": True}

    @pytest.mark.asyncio
    async def test_simple_call_with_suite_mix_from_other(self, dbsession):
        obj = StaticAnalysisSuiteFactory.create()
        another_obj_same_repo = StaticAnalysisSuiteFactory.create(
            commit__repository=obj.commit.repository
        )
        dbsession.add(obj)
        dbsession.flush()
        task = StaticAnalysisSuiteCheckTask()
        for i in range(17):
            fp_obj = StaticAnalysisSuiteFilepathFactory.create(
                analysis_suite=another_obj_same_repo,
                file_snapshot__state_id=StaticAnalysisSingleFileSnapshotState.CREATED.db_id,
            )
            dbsession.add(fp_obj)
        for i in range(23):
            fp_obj = StaticAnalysisSuiteFilepathFactory.create(
                analysis_suite=obj,
                file_snapshot__state_id=StaticAnalysisSingleFileSnapshotState.CREATED.db_id,
            )
            dbsession.add(fp_obj)
        for i in range(2):
            fp_obj = StaticAnalysisSuiteFilepathFactory.create(
                analysis_suite=obj,
                file_snapshot__state_id=StaticAnalysisSingleFileSnapshotState.VALID.db_id,
            )
            dbsession.add(fp_obj)
        dbsession.flush()
        res = await task.run_async(dbsession, suite_id=obj.id_)
        assert res == {"changed_count": 23, "successful": True}
