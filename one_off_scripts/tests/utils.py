import datetime as dt

import time_machine
from shared.django_apps.core.tests.factories import (
    RepositoryFactory,
)
from shared.django_apps.reports.tests.factories import (
    DailyTestRollupFactory,
    FlakeFactory,
    TestFactory,
    TestInstanceFactory,
)


def setup_one_off_tests():
    repo_1 = RepositoryFactory(test_analytics_enabled=True)

    test_1 = TestFactory(repository=repo_1)

    _ = FlakeFactory(
        test=test_1,
        repository=repo_1,
        start_date=dt.datetime.fromisoformat("1970-01-02T00:00:00Z"),
        end_date=dt.datetime.fromisoformat("1970-01-04T00:00:00Z"),
    )

    _ = FlakeFactory(
        test=test_1,
        repository=repo_1,
        start_date=dt.datetime.fromisoformat("1970-01-04T12:00:00Z"),
        end_date=None,
    )

    traveller = time_machine.travel("1970-01-01T00:00:00Z", tick=False)
    traveller.start()
    ti = TestInstanceFactory(test=test_1, duration_seconds=10.0)
    traveller.stop()

    traveller = time_machine.travel("1970-01-03T00:00:00Z", tick=False)
    traveller.start()
    ti = TestInstanceFactory(test=test_1, duration_seconds=10.0)
    traveller.stop()

    traveller = time_machine.travel("1970-01-05T00:00:00Z", tick=False)
    traveller.start()
    ti = TestInstanceFactory(
        test=test_1,
        duration_seconds=10000.0,
    )
    traveller.stop()

    _ = DailyTestRollupFactory(
        test=test_1,
        date=dt.date.fromisoformat("1970-01-03"),
        fail_count=10,
        pass_count=5,
        last_duration_seconds=10.0,
        avg_duration_seconds=1.0,
        latest_run=dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
    )

    _ = DailyTestRollupFactory(
        test=test_1,
        date=dt.date.fromisoformat("1970-01-05"),
        fail_count=10,
        pass_count=5,
        last_duration_seconds=10.0,
        avg_duration_seconds=1.0,
        latest_run=dt.datetime.fromisoformat("1970-01-01T00:00:00Z"),
    )

    _ = RepositoryFactory(test_analytics_enabled=False)

    return repo_1
