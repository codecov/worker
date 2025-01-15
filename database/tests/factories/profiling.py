import factory

from database.models.profiling import ProfilingCommit, ProfilingUpload
from database.tests.factories.core import RepositoryFactory


class ProfilingCommitFactory(factory.Factory):
    version_identifier = factory.Faker("slug")
    repository = factory.SubFactory(RepositoryFactory)

    class Meta:
        model = ProfilingCommit


class ProfilingUploadFactory(factory.Factory):
    profiling_commit = factory.SubFactory(ProfilingCommitFactory)
    raw_upload_location = factory.Faker("url")

    class Meta:
        model = ProfilingUpload
