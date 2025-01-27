import json
from pathlib import Path

import pytest

from database.tests.factories.profiling import (
    ProfilingUploadFactory,
)
from tasks.profiling_normalizer import ProfilingNormalizerTask

here = Path(__file__)


@pytest.fixture
def sample_open_telemetry_upload():
    with open(here.parent / "samples/sample_opentelem_input.json", "r") as file:
        return json.load(file)


@pytest.fixture
def sample_open_telemetry_normalized():
    with open(here.parent / "samples/sample_opentelem_normalized.json", "r") as file:
        return json.load(file)


def test_run_impl_simple_normalizing_run(
    dbsession,
    mock_storage,
    mock_configuration,
    mock_redis,
    mocker,
    sample_open_telemetry_upload,
    sample_open_telemetry_normalized,
):
    puf = ProfilingUploadFactory.create(
        profiling_commit__repository__yaml={
            "profiling": {"grouping_attributes": ["http.method", "celery.state"]},
            "codecov": {"max_report_age": None},
        },
        raw_upload_location="raw_upload_location",
    )
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    mock_storage.write_file(
        "bucket", "raw_upload_location", json.dumps(sample_open_telemetry_upload)
    )
    dbsession.add(puf)
    dbsession.flush()
    task = ProfilingNormalizerTask()
    res = task.run_impl(dbsession, profiling_upload_id=puf.id)
    assert res["successful"]
    result = json.loads(mock_storage.read_file("bucket", res["location"]).decode())
    assert result == sample_open_telemetry_normalized


def test_run_sync_normalizing_run_no_file(dbsession, mock_storage, mock_configuration):
    puf = ProfilingUploadFactory.create(
        profiling_commit__repository__yaml={"codecov": {"max_report_age": None}},
        raw_upload_location="raw_upload_location",
    )
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    dbsession.add(puf)
    dbsession.flush()
    task = ProfilingNormalizerTask()
    res = task.run_impl(dbsession, profiling_upload_id=puf.id)
    assert res == {"successful": False}
