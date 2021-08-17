import pytest

from database.enums import CompareCommitState
from database.tests.factories import CompareCommitFactory
from tasks.compute_comparison import ComputeComparisonTask


class TestComputeComparisonTask(object):
    @pytest.mark.asyncio
    async def test_set_state_to_processed(self, dbsession):
        comparison = CompareCommitFactory.create()
        dbsession.add(comparison)
        dbsession.flush()
        task = ComputeComparisonTask()
        await task.run_async(dbsession, comparison.id)
        dbsession.commit()
        dbsession.refresh(comparison)
        dbsession.flush()
        assert comparison.state is CompareCommitState.processed
