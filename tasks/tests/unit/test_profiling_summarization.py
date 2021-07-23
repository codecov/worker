import json

import pytest

from tasks.profiling_summarization import ProfilingSummarizationTask
from database.tests.factories.profiling import ProfilingCommitFactory


@pytest.mark.asyncio
async def test_summarize_run_async_simple_run(
    dbsession, mock_storage, mock_configuration
):
    data = {
        "metadata": {"version": "v7"},
        "files": [
            {
                "filename": "abc.py",
                "ln_ex_ct": [(2, 242), (3, 932), (5, 663), (7, 653), (8, 180)],
            },
            {
                "filename": "bcd.py",
                "ln_ex_ct": [(1, 728), (4, 198), (7, 348), (8, 827)],
            },
            {"filename": "cde.py", "ln_ex_ct": [(4, 967), (5, 305)]},
            {
                "filename": "def.py",
                "ln_ex_ct": [(3, 705), (4, 676), (5, 164), (6, 225), (8, 75), (9, 331)],
            },
        ],
    }
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    mock_storage.write_file("bucket", "path/b/c/d", json.dumps(data))
    pfc = ProfilingCommitFactory.create(joined_location="path/b/c/d")
    dbsession.add(pfc)
    dbsession.flush()
    task = ProfilingSummarizationTask()
    res = await task.run_async(dbsession, profiling_id=pfc.id)
    assert res["successful"]
    assert json.loads(mock_storage.read_file("bucket", res["location"]).decode()) == {
        "version": "v1",
        "general": {"total_profiled_files": 4},
        "file_groups": {
            "sum_of_executions": {"top_10_percent": [], "above_1_stdev": ["abc.py"]},
            "max_number_of_executions": {"top_10_percent": [], "above_1_stdev": []},
            "avg_number_of_executions": {
                "top_10_percent": [],
                "above_1_stdev": ["cde.py"],
            },
        },
    }


@pytest.mark.asyncio
async def test_summarize_run_async_simple_run_no_file(
    dbsession, mock_storage, mock_configuration
):
    mock_configuration._params["services"]["minio"]["bucket"] = "bucket"
    pfc = ProfilingCommitFactory.create(joined_location="path/b/c/d")
    dbsession.add(pfc)
    dbsession.flush()
    task = ProfilingSummarizationTask()
    res = await task.run_async(dbsession, profiling_id=pfc.id)
    assert res == {"successful": False}


def test_summarize_simple_case():
    given_input = {
        "metadata": {"version": "v7"},
        "files": [
            {
                "filename": "abc.py",
                "ln_ex_ct": [(2, 242), (3, 932), (5, 663), (7, 653), (8, 180)],
            },
            {
                "filename": "bcd.py",
                "ln_ex_ct": [(1, 728), (4, 198), (7, 348), (8, 827)],
            },
            {"filename": "cde.py", "ln_ex_ct": [(4, 967), (5, 305)]},
            {
                "filename": "def.py",
                "ln_ex_ct": [(3, 705), (4, 676), (5, 164), (6, 225), (8, 75), (9, 331)],
            },
            {
                "filename": "efg.py",
                "ln_ex_ct": [
                    (0, 570),
                    (1, 854),
                    (2, 769),
                    (3, 982),
                    (4, 646),
                    (5, 718),
                    (6, 931),
                    (7, 203),
                    (8, 885),
                    (9, 188),
                ],
            },
            {
                "filename": "egh.py",
                "ln_ex_ct": [(4, 357), (5, 601), (6, 861), (7, 212)],
            },
            {
                "filename": "ghi.py",
                "ln_ex_ct": [
                    (0, 443),
                    (1, 502),
                    (2, 17),
                    (5, 388),
                    (6, 617),
                    (7, 584),
                    (8, 203),
                    (9, 499),
                ],
            },
            {"filename": "hij.py", "ln_ex_ct": [(0, 190), (3, 834), (6, 944)]},
            {"filename": "ijk.py", "ln_ex_ct": [(2, 786), (3, 494), (9, 339)]},
            {
                "filename": "jkl.py",
                "ln_ex_ct": [(2, 925), (3, 303), (6, 809), (8, 63), (9, 869)],
            },
            {
                "filename": "klm.py",
                "ln_ex_ct": [(2, 1000), (3, 0), (6, 0), (8, 0), (9, 0)],
            },
            {"filename": "lmn.py", "ln_ex_ct": [(28, 999)]},
        ],
    }
    task = ProfilingSummarizationTask()
    expected_result = {
        "version": "v1",
        "general": {"total_profiled_files": 12},
        "file_groups": {
            "sum_of_executions": {
                "top_10_percent": ["efg.py"],
                "above_1_stdev": ["efg.py"],
            },
            "max_number_of_executions": {
                "top_10_percent": ["klm.py"],
                "above_1_stdev": [],
            },
            "avg_number_of_executions": {
                "top_10_percent": ["lmn.py"],
                "above_1_stdev": ["lmn.py"],
            },
        },
    }
    res = task.summarize(given_input)
    assert expected_result["file_groups"] == res["file_groups"]
    assert expected_result == res
