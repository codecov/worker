from uuid import uuid4

import factory
from shared.labelanalysis import LabelAnalysisRequestState

from database.models.staticanalysis import (
    StaticAnalysisSingleFileSnapshot,
    StaticAnalysisSuite,
    StaticAnalysisSuiteFilepath,
)
from database.tests.factories.core import CommitFactory, RepositoryFactory


class StaticAnalysisSuiteFactory(factory.Factory):
    class Meta:
        model = StaticAnalysisSuite

    commit = factory.SubFactory(CommitFactory)


class StaticAnalysisSingleFileSnapshotFactory(factory.Factory):
    class Meta:
        model = StaticAnalysisSingleFileSnapshot

    repository = factory.SubFactory(RepositoryFactory)
    file_hash = factory.LazyFunction(lambda: uuid4().hex)
    content_location = factory.Faker("file_path", depth=3)
    state_id = LabelAnalysisRequestState.CREATED.db_id


class StaticAnalysisSuiteFilepathFactory(factory.Factory):
    class Meta:
        model = StaticAnalysisSuiteFilepath

    filepath = factory.Faker("file_name")
    file_snapshot = factory.SubFactory(StaticAnalysisSingleFileSnapshotFactory)
    analysis_suite = factory.SubFactory(StaticAnalysisSuiteFactory)
