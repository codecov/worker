from pathlib import Path

from database.tests.factories import CommitFactory, PullFactory, RepositoryFactory
from services.archive import ArchiveService
from tasks.sync_pull import PullSyncTask

here = Path(__file__)


class TestPullSyncTask(object):
    def test_call_task(self, dbsession, codecov_vcr, mock_storage, mocker, mock_redis):
        mocker.patch.object(PullSyncTask, "app")
        task = PullSyncTask()
        repository = RepositoryFactory.create(
            owner__username="ThiagoCodecov",
            owner__service="github",
            owner__service_id="44376991",
            name="example-python",
            owner__unencrypted_oauth_token="testduhiiri16grurxduwjexioy26ohqhaxvk67z",
        )
        report_json = {
            "files": {
                "README.md": [
                    2,
                    [0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0]],
                    [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
                ],
                "codecov.yaml": [
                    0,
                    [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
                "tests/test_sample.py": [
                    1,
                    [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                    [[0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "N": None,
                    "a": "v4/raw/2019-01-10/4434BC2A2EC4FCA57F77B473D83F928C/abf6d4df662c47e32460020ab14abf9303581429/9ccc55a1-8b41-4bb1-a946-ee7a33a7fb56.txt",
                    "c": None,
                    "d": 1547084427,
                    "e": None,
                    "f": ["unit"],
                    "j": None,
                    "n": None,
                    "p": None,
                    "t": [3, 20, 17, 3, 0, "85.00000", 0, 0, 0, 0, 0, 0, 0],
                    "": None,
                }
            },
        }
        dbsession.add(repository)
        dbsession.flush()
        base_commit = CommitFactory.create(
            repository=repository, commitid="7a7153d24f76c9ad58f421bcac8276203d589b1a"
        )
        head_commit = CommitFactory.create(
            repository=repository,
            commitid="6dc3afd80a8deea5ea949d284d996d58811cd01d",
            branch="new_branch",
            _report_json=report_json,
        )
        archive_hash = ArchiveService.get_archive_hash(repository)
        with open(here.parent.parent / "samples" / "sample_chunks_1.txt") as f:
            head_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{head_commit.commitid}/chunks.txt"
            )
            content = f.read()
            mock_storage.write_file("archive", head_chunks_url, content)
        pull = PullFactory.create(
            pullid=17,
            repository=repository,
            base=base_commit.commitid,
            head=head_commit.commitid,
        )
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        res = task.run_impl(dbsession, repoid=pull.repoid, pullid=pull.pullid)
        assert {
            "notifier_called": True,
            "commit_updates_done": {"merged_count": 0, "soft_deleted_count": 0},
            "pull_updated": True,
            "reason": "success",
        } == res
        assert len(pull.flare) == 1
        expected_flare = {
            "_class": None,
            "children": [
                {
                    "_class": None,
                    "color": "red",
                    "coverage": -1,
                    "lines": 10,
                    "name": "README.md",
                },
                {
                    "_class": None,
                    "color": "#e1e1e1",
                    "coverage": 0,
                    "lines": 3,
                    "name": "codecov.yaml",
                },
                {
                    "_class": None,
                    "children": [
                        {
                            "_class": None,
                            "color": "#e1e1e1",
                            "coverage": 0,
                            "lines": 7,
                            "name": "test_sample.py",
                        }
                    ],
                    "color": "#e1e1e1",
                    "coverage": 0.0,
                    "lines": 7,
                    "name": "tests",
                },
            ],
            "color": "#e1e1e1",
            "coverage": 0.0,
            "lines": 20,
            "name": "",
        }
        assert expected_flare["children"] == pull.flare[0]["children"]
        assert expected_flare == pull.flare[0]
        assert pull.diff is None
