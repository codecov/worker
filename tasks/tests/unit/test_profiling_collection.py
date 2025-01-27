import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from redis.exceptions import LockError
from shared.storage.exceptions import FileNotInStorageError

from database.tests.factories.profiling import (
    ProfilingCommitFactory,
    ProfilingUploadFactory,
)
from helpers.clock import get_utc_now
from tasks.profiling_collection import ProfilingCollectionTask

here = Path(__file__)


@pytest.fixture
def sample_open_telemetry_normalized():
    with open(here.parent / "samples/sample_opentelem_normalized.json", "r") as file:
        return json.load(file)


@pytest.fixture
def sample_open_telemetry_collected():
    with open(here.parent / "samples/sample_opentelem_collected.json", "r") as file:
        return json.load(file)


def test_run_impl_simple_run_no_existing_data(
    dbsession, mock_storage, mock_configuration, mock_redis, mocker
):
    mock_delay = mocker.patch("tasks.profiling_collection.profiling_summarization_task")
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    pcf = ProfilingCommitFactory.create(joined_location=None)
    dbsession.add(pcf)
    dbsession.flush()
    task = ProfilingCollectionTask()
    res = task.run_impl(dbsession, profiling_id=pcf.id)
    assert res["successful"]
    assert json.loads(mock_storage.read_file("bucket", res["location"]).decode()) == {
        "files": [],
        "groups": [],
        "metadata": {"version": "v1"},
    }
    mock_delay.delay.assert_called_with(profiling_id=pcf.id)


def test_run_impl_simple_run_no_existing_data_yes_new_uploads(
    dbsession, mock_storage, mock_configuration, mock_redis, mocker
):
    mock_delay = mocker.patch("tasks.profiling_collection.profiling_summarization_task")
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    mock_storage.write_file(
        "bucket",
        "raw_upload_location",
        json.dumps(
            {
                "runs": [
                    {
                        "group": "fruit group",
                        "execs": [
                            {"filename": "banana.py", "lines": {"5": 10, "68": 87}}
                        ],
                    }
                ]
            }
        ),
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
    res = task.run_impl(dbsession, profiling_id=pcf.id)
    assert res["successful"]
    assert json.loads(mock_storage.read_file("bucket", res["location"]).decode()) == {
        "groups": [
            {
                "count": 1,
                "group_name": "fruit group",
                "files": [{"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}],
            }
        ],
        "files": [{"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}],
        "metadata": {"version": "v1"},
    }
    mock_delay.delay.assert_called_with(profiling_id=pcf.id)


def test_run_impl_simple_run_no_existing_data_sample_new_uploads(
    dbsession,
    mock_storage,
    mock_configuration,
    mock_redis,
    mocker,
    sample_open_telemetry_normalized,
    sample_open_telemetry_collected,
):
    mock_delay = mocker.patch("tasks.profiling_collection.profiling_summarization_task")
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    mock_storage.write_file(
        "bucket", "raw_upload_location", json.dumps(sample_open_telemetry_normalized)
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
    res = task.run_impl(dbsession, profiling_id=pcf.id)
    assert res["successful"]
    assert (
        json.loads(mock_storage.read_file("bucket", res["location"]).decode())
        == sample_open_telemetry_collected
    )
    mock_delay.delay.assert_called_with(profiling_id=pcf.id)


def test_collection_task_redis_lock_unavailable(dbsession, mocker, mock_redis):
    pcf = ProfilingCommitFactory.create(joined_location=None)
    dbsession.add(pcf)
    dbsession.flush()
    task = ProfilingCollectionTask()
    mock_redis.lock.return_value.__enter__.side_effect = LockError()
    res = task.run_impl(dbsession, profiling_id=pcf.id)
    assert res == {"location": None, "successful": False, "summarization_task_id": None}


class TestProfilingCollectionTask(object):
    def test_join_profiling_uploads_no_existing_data_no_new_uploads(
        self, dbsession, mock_storage
    ):
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(joined_location=None)
        dbsession.add(pcf)
        dbsession.flush()
        res = task.join_profiling_uploads(pcf, [])
        assert res == {"groups": [], "files": [], "metadata": {"version": "v1"}}

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
                    "groups": [
                        {
                            "count": 2,
                            "files": [
                                {
                                    "filename": "banana.py",
                                    "ln_ex_ct": [[5, 10], [68, 87]],
                                }
                            ],
                            "group_name": "abcde",
                        }
                    ],
                    "files": [
                        {"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}
                    ],
                    "metadata": {"version": "v1"},
                }
            ),
        )
        res = task.join_profiling_uploads(pcf, [])
        assert res == {
            "groups": [
                {
                    "count": 2,
                    "files": [
                        {"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}
                    ],
                    "group_name": "abcde",
                }
            ],
            "files": [{"filename": "banana.py", "ln_ex_ct": [(5, 10), (68, 87)]}],
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
                    "groups": [
                        {
                            "files": [
                                {
                                    "filename": "banana.py",
                                    "ln_ex_ct": [[5, 10], [68, 87]],
                                }
                            ],
                            "group_name": "POST /def",
                            "count": 90,
                        }
                    ],
                    "files": [
                        {"filename": "banana.py", "ln_ex_ct": [[5, 10], [68, 87]]}
                    ],
                    "metadata": {"version": "v1"},
                }
            ),
        )
        mock_storage.write_file(
            "bucket",
            "normalized_pu_location",
            json.dumps(
                {
                    "runs": [
                        {
                            "group": "GET /abc",
                            "execs": [
                                {"filename": "apple.py", "lines": {"2": 10, "101": 11}},
                                {"filename": "banana.py", "lines": {"5": 1, "6": 2}},
                            ],
                        },
                        {
                            "group": "POST /def",
                            "execs": [
                                {"filename": "banana.py", "lines": {"1": 1, "6": 2}},
                                {"filename": "sugar.py", "lines": {"1": 100}},
                            ],
                        },
                    ]
                }
            ),
        )
        pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=get_utc_now() - timedelta(seconds=120),
            normalized_location="normalized_pu_location",
        )
        dbsession.add(pu)
        dbsession.flush()
        res = task.join_profiling_uploads(pcf, [pu])
        assert res == {
            "groups": [
                {
                    "files": [
                        {
                            "filename": "banana.py",
                            "ln_ex_ct": [(1, 1), (5, 10), (6, 2), (68, 87)],
                        },
                        {"filename": "sugar.py", "ln_ex_ct": [(1, 100)]},
                    ],
                    "group_name": "POST /def",
                    "count": 91,
                },
                {
                    "group_name": "GET /abc",
                    "files": [
                        {"filename": "apple.py", "ln_ex_ct": [(2, 10), (101, 11)]},
                        {"filename": "banana.py", "ln_ex_ct": [(5, 1), (6, 2)]},
                    ],
                    "count": 1,
                },
            ],
            "files": [
                {
                    "filename": "banana.py",
                    "ln_ex_ct": [(1, 1), (5, 11), (6, 4), (68, 87)],
                },
                {"filename": "sugar.py", "ln_ex_ct": [(1, 100)]},
                {"filename": "apple.py", "ln_ex_ct": [(2, 10), (101, 11)]},
            ],
            "metadata": {"version": "v1"},
        }

    def test_join_profiling_uploads_with_existing_data_and_sample_uploads(
        self,
        dbsession,
        mock_storage,
        mock_configuration,
        sample_open_telemetry_normalized,
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
                    "groups": [
                        {
                            "group_name": "OPTIONS /banana",
                            "files": [
                                {
                                    "filename": "helpers/logging_config.py",
                                    "ln_ex_ct": [[5, 10], [28, 87]],
                                }
                            ],
                            "count": 100,
                        }
                    ],
                    "files": [
                        {
                            "filename": "helpers/logging_config.py",
                            "ln_ex_ct": [[5, 10], [28, 87]],
                        }
                    ],
                    "metadata": {"version": "v1"},
                }
            ),
        )
        mock_storage.write_file(
            "bucket",
            "raw_upload_location",
            json.dumps(sample_open_telemetry_normalized),
        )
        pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=get_utc_now() - timedelta(seconds=120),
            normalized_location="raw_upload_location",
        )
        dbsession.add(pu)
        dbsession.flush()
        res = task.join_profiling_uploads(pcf, [pu])
        assert (sorted(x["filename"] for x in res["files"])) == [
            "database/base.py",
            "database/engine.py",
            "database/models/core.py",
            "database/models/reports.py",
            "helpers/cache.py",
            "helpers/logging_config.py",
            "helpers/pathmap/pathmap.py",
            "helpers/pathmap/tree.py",
            "services/archive.py",
            "services/bots.py",
            "services/path_fixer/__init__.py",
            "services/path_fixer/fixpaths.py",
            "services/path_fixer/user_path_fixes.py",
            "services/path_fixer/user_path_includes.py",
            "services/redis.py",
            "services/report/__init__.py",
            "services/report/languages/base.py",
            "services/report/languages/clover.py",
            "services/report/languages/cobertura.py",
            "services/report/languages/csharp.py",
            "services/report/languages/helpers.py",
            "services/report/languages/jacoco.py",
            "services/report/languages/jetbrainsxml.py",
            "services/report/languages/mono.py",
            "services/report/languages/scoverage.py",
            "services/report/languages/vb.py",
            "services/report/languages/vb2.py",
            "services/report/parser.py",
            "services/report/raw_upload_processor.py",
            "services/report/report_processor.py",
            "services/repository.py",
            "services/storage.py",
            "services/yaml/reader.py",
            "tasks/base.py",
            "tasks/upload.py",
            "tasks/upload_processor.py",
        ]
        assert sorted(x["group_name"] for x in res["groups"]) == [
            "OPTIONS /banana",
            "run/app.tasks.upload.Upload",
            "run/app.tasks.upload_processor.UploadProcessorTask",
        ]
        # Asserting them all will produce a huge file. We will leave that full comparison
        # to a different test
        filename_mapping = {data["filename"]: data for data in res["files"]}
        assert filename_mapping["services/report/languages/mono.py"] == {
            "filename": "services/report/languages/mono.py",
            "ln_ex_ct": [(9, 2)],
        }
        assert filename_mapping["helpers/logging_config.py"] == {
            "filename": "helpers/logging_config.py",
            "ln_ex_ct": [
                (5, 10),
                (11, 5),
                (12, 5),
                (13, 5),
                (14, 5),
                (15, 5),
                (24, 5),
                (25, 5),
                (26, 5),
                (27, 5),
                (28, 92),
                (30, 5),
            ],
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
        existing_result = {"files": [], "groups": []}
        res = task.merge_into(archive_service, existing_result, [pu])
        assert res is None
        assert existing_result == {"files": [], "groups": []}

    def test_merge_into_upload_file_old_result(self, dbsession, mock_storage, mocker):
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(joined_location="location")
        dbsession.add(pcf)
        dbsession.flush()
        pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=get_utc_now() - timedelta(seconds=120),
            normalized_location="normalized_pu_location",
        )
        dbsession.add(pu)
        dbsession.flush()
        archive_service = mocker.MagicMock(
            read_file=mocker.MagicMock(
                return_value=json.dumps(
                    {
                        "runs": [
                            {
                                "group": "GET /abc",
                                "execs": [
                                    {
                                        "filename": "apple.py",
                                        "lines": {"2": 10, "101": 11},
                                    },
                                    {
                                        "filename": "banana.py",
                                        "lines": {"5": 1, "6": 2},
                                    },
                                ],
                            },
                            {
                                "group": "POST /def",
                                "execs": [
                                    {
                                        "filename": "banana.py",
                                        "lines": {"1": 1, "6": 2},
                                    },
                                    {"filename": "sugar.py", "lines": {"1": 100}},
                                ],
                            },
                        ]
                    }
                )
            )
        )
        existing_result = {"files": []}
        res = task.merge_into(archive_service, existing_result, [pu])
        assert res is None
        assert existing_result == {
            "files": [
                {"filename": "apple.py", "ln_ex_ct": [(2, 10), (101, 11)]},
                {"filename": "banana.py", "ln_ex_ct": [(1, 1), (5, 1), (6, 4)]},
                {"filename": "sugar.py", "ln_ex_ct": [(1, 100)]},
            ],
            "groups": [
                {
                    "group_name": "GET /abc",
                    "files": [
                        {"filename": "apple.py", "ln_ex_ct": [(2, 10), (101, 11)]},
                        {"filename": "banana.py", "ln_ex_ct": [(5, 1), (6, 2)]},
                    ],
                    "count": 1,
                },
                {
                    "group_name": "POST /def",
                    "files": [
                        {"filename": "banana.py", "ln_ex_ct": [(1, 1), (6, 2)]},
                        {"filename": "sugar.py", "ln_ex_ct": [(1, 100)]},
                    ],
                    "count": 1,
                },
            ],
        }

    def test_find_uploads_to_join_first_joining(self, dbsession):
        before = datetime(2021, 5, 2, 0, 3, 4).replace(tzinfo=timezone.utc)
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create()
        another_pfc = ProfilingCommitFactory.create()
        dbsession.add(pcf)
        dbsession.add(another_pfc)
        dbsession.flush()
        first_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=datetime(2021, 5, 1, 0, 12, 14).replace(tzinfo=timezone.utc),
        )
        second_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=datetime(2021, 6, 10, 0, 12, 14).replace(tzinfo=timezone.utc),
        )
        dbsession.add(first_pu)
        dbsession.add(second_pu)
        res, when = task.find_uploads_to_join(pcf, before)
        assert list(res) == [first_pu]
        assert when == datetime(2021, 5, 1, 0, 12, 14).replace(tzinfo=timezone.utc)
        # ensuring we don't get data from different pfcs
        another_res, another_when = task.find_uploads_to_join(another_pfc, before)
        assert list(another_res) == []
        assert another_when == before

    def test_find_uploads_to_join_already_joined(self, dbsession):
        before = datetime(2021, 5, 1, 4, 0, 0).replace(tzinfo=timezone.utc)
        task = ProfilingCollectionTask()
        pcf = ProfilingCommitFactory.create(
            last_joined_uploads_at=datetime(2021, 5, 1, 1, 2, 3)
        )
        dbsession.add(pcf)
        dbsession.flush()
        first_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=datetime(2021, 5, 1, 1, 1, 1).replace(tzinfo=timezone.utc),
        )
        second_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=datetime(2021, 5, 1, 1, 30, 0).replace(tzinfo=timezone.utc),
        )
        third_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=datetime(2021, 5, 1, 2, 1, 0).replace(tzinfo=timezone.utc),
        )
        fourth_pu = ProfilingUploadFactory.create(
            profiling_commit=pcf,
            normalized_at=datetime(2021, 5, 1, 4, 12, 14).replace(tzinfo=timezone.utc),
        )
        dbsession.add(first_pu)
        dbsession.add(second_pu)
        dbsession.add(third_pu)
        dbsession.add(fourth_pu)
        res, when = task.find_uploads_to_join(pcf, before)
        assert list(res) == [second_pu, third_pu]
        assert when == third_pu.normalized_at
        limited_res, limited_when = task.find_uploads_to_join(
            pcf, before, max_number_of_results=1
        )
        assert list(limited_res) == [second_pu]
        assert limited_when == second_pu.normalized_at
