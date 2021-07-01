from tasks.profiling_summarization import ProfilingSummarizationTask


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
        ],
    }
    task = ProfilingSummarizationTask()
    expected_result = {
        "file_groups": {
            "sum_of_executions": {
                "top_10_percent": ["efg.py"],
                "above_1_stdev": ["efg.py"],
            }
        }
    }
    res = task.summarize(given_input)
    print(res)
    assert expected_result == task.summarize(given_input)
