import factory

from database.models import LabelAnalysisRequest
from database.tests.factories.core import CommitFactory


class LabelAnalysisRequestFactory(factory.Factory):
    class Meta:
        model = LabelAnalysisRequest

    base_commit = factory.SubFactory(CommitFactory)
    head_commit = factory.SubFactory(CommitFactory)
    state_id = 1
