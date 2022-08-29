import pytest

from database.tests.factories import RepositoryFactory
from database.tests.factories.labelanalysis import LabelAnalysisRequestFactory
from tasks.label_analysis import (
    LabelAnalysisRequestProcessingTask,
    LabelAnalysisRequestState,
)


@pytest.mark.asyncio
async def test_simple_label_request_call(dbsession):
    repository = RepositoryFactory.create()
    larf = LabelAnalysisRequestFactory.create(
        base_commit__repository=repository, head_commit__repository=repository
    )
    dbsession.add(larf)
    dbsession.flush()
    task = LabelAnalysisRequestProcessingTask()
    res = await task.run_async(dbsession, larf.id)
    expected_result = {"success": True}
    assert res == expected_result
    dbsession.flush()
    dbsession.refresh(larf)
    assert larf.state_id == LabelAnalysisRequestState.finished.value
    assert larf.result == {"not": "ready"}
