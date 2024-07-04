import factory
from test_results_parser import Outcome

from database.models.reports import (
    CompareFlag,
    Flake,
    ReducedError,
    RepositoryFlag,
    Test,
    TestInstance,
)
from database.tests.factories.core import (
    CompareCommitFactory,
    RepositoryFactory,
    UploadFactory,
)
from services.failure_normalizer import reduce_error
from services.test_results import generate_test_id


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


class ReducedErrorFactory(factory.Factory):
    class Meta:
        model = ReducedError

    class Params:
        failure_message = factory.Sequence(lambda n: f"message_{n}")

    message = factory.LazyAttribute(lambda o: reduce_error(o.failure_message))


class TestFactory(factory.Factory):
    class Meta:
        model = Test

    repository = factory.SubFactory(RepositoryFactory)
    name = factory.Sequence(lambda n: f"name_{n}\x1f{n}")
    testsuite = factory.Sequence(lambda n: f"testsuite_{n}")
    flags_hash = factory.Sequence(lambda n: f"flag_{n}")
    id_ = factory.LazyAttribute(
        lambda o: generate_test_id(
            o.repository.repoid, o.testsuite, o.name, o.flags_hash
        )
    )


class TestInstanceFactory(factory.Factory):
    class Meta:
        model = TestInstance

    upload = factory.SubFactory(UploadFactory)
    test = factory.SubFactory(TestFactory)

    reduced_error = factory.SubFactory(
        ReducedErrorFactory, failure_message=factory.Sequence(lambda n: f"message_{n}")
    )

    outcome = str(Outcome.Failure)

    failure_message = factory.Sequence(lambda n: f"message_{n}")
    duration_seconds = duration_seconds = factory.Faker(
        "pyint", min_value=0, max_value=1000
    )


class FlakeFactory(factory.Factory):
    class Meta:
        model = Flake

    repository = factory.SubFactory(RepositoryFactory)
    test = factory.SubFactory(TestFactory)
    reduced_error = factory.SubFactory(ReducedErrorFactory)
