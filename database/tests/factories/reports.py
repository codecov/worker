import factory

from database.models.reports import CompareFlag, RepositoryFlag, Test
from database.tests.factories.core import CompareCommitFactory, RepositoryFactory


class RepositoryFlagFactory(factory.Factory):
    repository = factory.SubFactory(RepositoryFactory)
    flag_name = factory.Sequence(lambda n: f"flag{n}")

    class Meta:
        model = RepositoryFlag


class CompareFlagFactory(factory.Factory):
    class Meta:
        model = CompareFlag

    commit_comparison = factory.SubFactory(CompareCommitFactory)
    repositoryflag = factory.SubFactory(RepositoryFlagFactory)


class TestFactory(factory.Factory):
    class Meta:
        model = Test

    name = factory.Sequence(lambda n: f"test_{n}")
    testsuite = "testsuite"
    flags_hash = "flags_hash"
    id_ = factory.Sequence(lambda n: f"id_{n}")
    repository = factory.SubFactory(RepositoryFactory)
