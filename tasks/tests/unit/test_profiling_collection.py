import json
from datetime import datetime, timedelta

import pytest
from shared.storage.exceptions import FileNotInStorageError

from database.tests.factories.profiling import (
    ProfilingCommitFactory,
    ProfilingUploadFactory,
)
from helpers.clock import get_utc_now
from tasks.profiling_collection import ProfilingCollectionTask


@pytest.mark.asyncio
async def test_run_async_simple_run_no_existing_data(
    dbsession, mock_storage, mock_configuration, mock_redis, mocker
):
    mock_delay = mocker.patch("tasks.profiling_collection.profiling_summarization_task")
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    pcf = ProfilingCommitFactory.create(joined_location=None)
    dbsession.add(pcf)
    dbsession.flush()
    task = ProfilingCollectionTask()
    res = await task.run_async(dbsession, profiling_id=pcf.id)
    assert res["successful"]
    assert json.loads(mock_storage.read_file("bucket", res["location"]).decode()) == {
        "files": [],
        "metadata": {"version": "v1"},
    }
    mock_delay.delay.assert_called_with(profiling_id=pcf.id)


@pytest.mark.asyncio
async def test_run_async_simple_run_no_existing_data_new_uploads(
    dbsession, mock_storage, mock_configuration, mock_redis, mocker
):
    mock_delay = mocker.patch("tasks.profiling_collection.profiling_summarization_task")
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    mock_storage.write_file(
        "bucket",
        "raw_upload_location",
        json.dumps({"files": {"banana.py": {"5": 10, "68": 87}}}),
    )
    pcf = ProfilingCommitFactory.create(joined_location=None)
    dbsession.add(pcf)
    dbsession.flush()
    pu = ProfilingUploadFactory.create(
        profiling_commit=pcf,
        normalized_at=get_utc_now() - timedelta(seconds=120),
        normalized_location="raw_upload_location",
    )
    dbsession.add(pu)
    dbsession.flush()
    task = ProfilingCollectionTask()
    res = await task.run_async(dbsession, profiling_id=pcf.id)
    assert res["successful"]
    assert json.loads(mock_storage.read_file("bucket", res["location"]).decode()) == {
        "files": [{"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}],
        "metadata": {"version": "v1"},
    }
    mock_delay.delay.assert_called_with(profiling_id=pcf.id)


class TestProfilingCollectionTask(object):
    def test_join_profiling_uploads_no_existing_data_no_new_uploads(
        self, dbsession, mock_storage
    ):
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(joined_location=None)
        dbsession.add(pcf)
        dbsession.flush()
        res = task.join_profiling_uploads(pcf, [])
        assert res == {"files": [], "metadata": {"version": "v1"}}

    def test_join_profiling_uploads_with_existing_data_no_new_uploads(
        self, dbsession, mock_storage, mock_configuration
    ):
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(joined_location="location")
        dbsession.add(pcf)
        dbsession.flush()
        mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
        mock_storage.write_file(
            "bucket",
            "location",
            json.dumps(
                {
                    "files": [
                        {"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}
                    ],
                    "metadata": {"version": "v1"},
                }
            ),
        )
        res = task.join_profiling_uploads(pcf, [])
        assert res == {
            "files": [{"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}],
            "metadata": {"version": "v1"},
        }

    def test_join_profiling_uploads_with_existing_data_and_new_uploads(
        self, dbsession, mock_storage, mock_configuration
    ):
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(joined_location="location")
        dbsession.add(pcf)
        dbsession.flush()
        mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
        mock_storage.write_file(
            "bucket",
            "location",
            json.dumps(
                {
                    "files": [
                        {"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}
                    ],
                    "metadata": {"version": "v1"},
                }
            ),
        )
        mock_storage.write_file(
            "bucket",
            "raw_upload_location",
            json.dumps(
                {
                    "files": {
                        "apple.py": {"2": 10, "101": 11},
                        "banana.py": {"5": 1, "6": 2},
                    }
                }
            ),
        )
        pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=get_utc_now() - timedelta(seconds=120),
            normalized_location="raw_upload_location",
        )
        dbsession.add(pu)
        dbsession.flush()
        res = task.join_profiling_uploads(pcf, [pu])
        assert res == {
            "files": [
                {"filename": "banana.py", "ln_ex_ct": [(5, 11), (68, 87), (6, 2)]},
                {"filename": "apple.py", "ln_ex_ct": [(2, 10), (101, 11)]},
            ],
            "metadata": {"version": "v1"},
        }

    def test_merge_into_upload_file_does_not_exist(
        self, dbsession, mock_storage, mocker
    ):
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(joined_location="location")
        dbsession.add(pcf)
        dbsession.flush()
        pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=get_utc_now() - timedelta(seconds=120),
            normalized_location="raw_upload_location",
        )
        dbsession.add(pu)
        dbsession.flush()
        archive_service = mocker.MagicMock(
            read_file=mocker.MagicMock(side_effect=FileNotInStorageError)
        )
        existing_result = {"files": {}}
        res = task.merge_into(archive_service, existing_result, pu)
        assert res is None
        assert existing_result == {"files": {}}

    def test_find_uploads_to_join_first_joining(self, dbsession):
        before = datetime(2021, 5, 2, 0, 3, 4)
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create()
        another_pfc = ProfilingCommitFactory.create()
        dbsession.add(pcf)
        dbsession.add(another_pfc)
        dbsession.flush()
        first_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf, normalized_at=datetime(2021, 5, 1, 0, 12, 14)
        )
        second_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf, normalized_at=datetime(2021, 6, 10, 0, 12, 14)
        )
        dbsession.add(first_pu)
        dbsession.add(second_pu)
        res, when = task.find_uploads_to_join(pcf, before)
        assert list(res) == [first_pu]
        assert when == before
        # ensuring we don't get data from different pfcs
        another_res, another_when = task.find_uploads_to_join(another_pfc, before)
        assert list(another_res) == []
        assert another_when == before

    def test_find_uploads_to_join_already_joined(self, dbsession):
        before = datetime(2021, 5, 1, 4, 0, 0)
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(
            last_joined_uploads_at=datetime(2021, 5, 1, 1, 2, 3)
        )
        dbsession.add(pcf)
        dbsession.flush()
        first_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf, normalized_at=datetime(2021, 5, 1, 1, 1, 1)
        )
        second_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf, normalized_at=datetime(2021, 5, 1, 1, 30, 0)
        )
        third_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf, normalized_at=datetime(2021, 5, 1, 2, 1, 0)
        )
        fourth_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf, normalized_at=datetime(2021, 5, 1, 4, 12, 14)
        )
        dbsession.add(first_pu)
        dbsession.add(second_pu)
        dbsession.add(third_pu)
        dbsession.add(fourth_pu)
        res, when = task.find_uploads_to_join(pcf, before)
        assert list(res) == [second_pu, third_pu]
        assert when == before
