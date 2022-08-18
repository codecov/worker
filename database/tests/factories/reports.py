import factory

from database.models.reports import RepositoryFlag
from database.tests.factories.core import RepositoryFactory


class RepositoryFlagFactory(factory.Factory):

    repository = factory.SubFactory(RepositoryFactory)
    flag_name = factory.Sequence(lambda n: f"flag{n}")

    class Meta:
        model = RepositoryFlag
