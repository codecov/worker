from uuid import uuid4

import factory

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
    content_location = "a/b/c.txt"


class StaticAnalysisSuiteFilepathFactory(factory.Factory):
    class Meta:
        model = StaticAnalysisSuiteFilepath

    filepath = factory.Faker("file_name")
    file_snapshot = factory.SubFactory(StaticAnalysisSingleFileSnapshotFactory)
    analysis_suite = factory.SubFactory(StaticAnalysisSuiteFactory)
