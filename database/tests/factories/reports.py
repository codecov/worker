import datetime as dt

import factory

from database.models.reports import (
    CompareFlag,
    Flake,
    RepositoryFlag,
    Test,
    TestInstance,
    TestResultReportTotals,
)
from database.tests.factories.core import (
    CompareCommitFactory,
    ReportFactory,
    RepositoryFactory,
    UploadFactory,
)


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


class TestInstanceFactory(factory.Factory):
    class Meta:
        model = TestInstance

    test = factory.SubFactory(TestFactory)
    upload = factory.SubFactory(UploadFactory)

    outcome = "pass"
    duration_seconds = 1.5
    commitid = factory.SelfAttribute("upload.report.commit.commitid")
    branch = factory.SelfAttribute("upload.report.commit.branch")
    repoid = factory.SelfAttribute("upload.report.commit.repository.repoid")


class FlakeFactory(factory.Factory):
    class Meta:
        model = Flake

    test = factory.SubFactory(TestFactory)
    repository = factory.SelfAttribute("test.repository")
    reduced_error = None

    count = 0
    fail_count = 0
    recent_passes_count = 0

    start_date = dt.datetime.now()
    end_date = None


class TestResultReportTotalsFactory(factory.Factory):
    class Meta:
        model = TestResultReportTotals

    report = factory.SubFactory(ReportFactory)
    passed = 0
    skipped = 0
    failed = 0
