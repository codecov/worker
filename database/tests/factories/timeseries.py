import random
from datetime import datetime

import factory

from database.models.timeseries import Dataset, Measurement


class MeasurementFactory(factory.Factory):
    owner_id = 1
    repo_id = 1
    name = "testing"
    branch = "master"
    value = factory.LazyAttribute(lambda: random.random() * 1000)
    timestamp = factory.LazyAttribute(lambda: datetime.now())

    class Meta:
        model = Measurement


class DatasetFactory(factory.Factory):
    repository_id = 1
    name = "testing"
    backfilled = False

    class Meta:
        model = Dataset
