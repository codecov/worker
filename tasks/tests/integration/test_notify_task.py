from decimal import Decimal
from unittest.mock import patch

import pytest

from database.models import Pull
from database.tests.factories import CommitFactory, RepositoryFactory
from services.archive import ArchiveService
from services.notification.notifiers.base import NotificationResult
from tasks.notify import NotifyTask

sample_token = "ghp_test6ldgmyaglf73gcnbi0kprz7dyjz6nzgn"


@pytest.mark.integration
class TestNotifyTask(object):
    @patch("requests.post")
    @pytest.mark.asyncio
    async def test_simple_call_no_notifiers(
        self,
        mock_requests_post,
        dbsession,
        mocker,
        codecov_vcr,
        mock_storage,
        mock_configuration,
        mock_redis,
    ):
        mock_requests_post.return_value.status_code = 200
        mock_redis.get.return_value = False
        mock_configuration.params["setup"][
            "codecov_dashboard_url"
        ] = "https://codecov.io"
        mocked_app = mocker.patch.object(NotifyTask, "app")
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token=sample_token,
            owner__username="ThiagoCodecov",
            owner__service_id="44376991",
            owner__service="github",
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        master_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=repository,
            author__username="christina84",
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository=repository,
            author__username="christina84",
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
            master_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt"
            )
            mock_storage.write_file("archive", master_chunks_url, content)
        task = NotifyTask()
        result = await task.run_async(
            dbsession, repoid=commit.repoid, commitid=commit.commitid, current_yaml={}
        )
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "codecov-slack-app",
                    "title": "codecov-slack-app",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": "Successfully notified slack app",
                        "data_sent": {
                            "repository": "example-python",
                            "owner": "ThiagoCodecov",
                            "comparison": {
                                "url": None,
                                "message": "unknown",
                                "coverage": None,
                                "notation": "",
                                "head_commit": {
                                    "commitid": "649eaaf2924e92dc7fd8d370ddb857033231e67a",
                                    "branch": "test-branch-1",
                                    "message": "",
                                    "author": "christina84",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "base_commit": None,
                                "head_totals_c": "85.00000",
                            },
                        },
                        "data_received": None,
                    },
                }
            ],
        }
        assert result == expected_result

    @patch("requests.post")
    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers(
        self,
        mock_post_request,
        dbsession,
        mocker,
        codecov_vcr,
        mock_storage,
        mock_configuration,
    ):
        mock_post_request.return_value.status_code = 200
        mock_configuration.params["setup"][
            "codecov_dashboard_url"
        ] = "https://codecov.io"
        mocked_app = mocker.patch.object(NotifyTask, "app")
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token=sample_token,
            owner__username="ThiagoCodecov",
            owner__service="github",
            owner__service_id="44376991",
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        master_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=repository,
            author__username="bateslouis",
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository=repository,
            parent_commit_id="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            author__username="bateslouis",
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
            master_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt"
            )
            mock_storage.write_file("archive", master_chunks_url, content)
        result = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={"coverage": {"status": {"project": True}}},
        )
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "status-project",
                    "title": "default",
                    "result": {
                        "notification_attempted": False,
                        "notification_successful": None,
                        "explanation": "already_done",
                        "data_sent": {
                            "title": "codecov/project",
                            "state": "success",
                            "message": "85.00% (+0.00%) compared to 17a71a9",
                        },
                        "data_received": None,
                    },
                },
                {
                    "notifier": "codecov-slack-app",
                    "title": "codecov-slack-app",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": "Successfully notified slack app",
                        "data_sent": {
                            "repository": "example-python",
                            "owner": "ThiagoCodecov",
                            "comparison": {
                                "url": "https://codecov.io/gh/ThiagoCodecov/example-python/commit/649eaaf2924e92dc7fd8d370ddb857033231e67a",
                                "message": "no change",
                                "coverage": "0.00",
                                "notation": "",
                                "head_commit": {
                                    "commitid": "649eaaf2924e92dc7fd8d370ddb857033231e67a",
                                    "branch": "test-branch-1",
                                    "message": "",
                                    "author": "bateslouis",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "base_commit": {
                                    "commitid": "17a71a9a2f5335ed4d00496c7bbc6405f547a527",
                                    "branch": "master",
                                    "message": "",
                                    "author": "bateslouis",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "head_totals_c": "85.00000",
                            },
                        },
                        "data_received": None,
                    },
                },
            ],
        }
        assert (
            result["notifications"][0]["result"]
            == expected_result["notifications"][0]["result"]
        )
        assert result["notifications"][0] == expected_result["notifications"][0]
        assert result["notifications"] == expected_result["notifications"]
        assert result == expected_result

    @patch("requests.post")
    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers_no_pull_request(
        self,
        mock_post_request,
        dbsession,
        mocker,
        codecov_vcr,
        mock_storage,
        mock_configuration,
    ):
        mock_post_request.return_value.status_code = 200
        mock_configuration.params["setup"][
            "codecov_dashboard_url"
        ] = "https://myexamplewebsite.io"
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token=sample_token,
            owner__service="github",
            owner__username="ThiagoCodecov",
            owner__service_id="44376991",
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        parent_commit_id = "081d91921f05a8a39d39aef667eddb88e96300c7"
        commitid = "f0895290dc26668faeeb20ee5ccd4cc995925775"
        master_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid=parent_commit_id,
            repository=repository,
            author__username="bateslouis",
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid=commitid,
            parent_commit_id=master_commit.commitid,
            repository=repository,
            author__username="rolabuhasna",
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
            master_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt"
            )
            mock_storage.write_file("archive", master_chunks_url, content)
        result = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={
                "coverage": {
                    "status": {"project": True, "patch": True, "changes": True}
                }
            },
        )
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "status-project",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "title": "codecov/project",
                            "state": "success",
                            "message": "85.00% (+0.00%) compared to 081d919",
                        },
                        "data_received": {"id": 9333281614},
                    },
                },
                {
                    "notifier": "status-patch",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "title": "codecov/patch",
                            "state": "success",
                            "message": "Coverage not affected when comparing 081d919...f089529",
                        },
                        "data_received": {"id": 9333281697},
                    },
                },
                {
                    "notifier": "status-changes",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "title": "codecov/changes",
                            "state": "failure",
                            "message": "1 file has unexpected coverage changes not visible in diff",
                        },
                        "data_received": {"id": 9333281703},
                    },
                },
                {
                    "notifier": "codecov-slack-app",
                    "title": "codecov-slack-app",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": "Successfully notified slack app",
                        "data_sent": {
                            "repository": "example-python",
                            "owner": "ThiagoCodecov",
                            "comparison": {
                                "url": "https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/f0895290dc26668faeeb20ee5ccd4cc995925775",
                                "message": "no change",
                                "coverage": "0.00",
                                "notation": "",
                                "head_commit": {
                                    "commitid": "f0895290dc26668faeeb20ee5ccd4cc995925775",
                                    "branch": "test-branch-1",
                                    "message": "",
                                    "author": "rolabuhasna",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "base_commit": {
                                    "commitid": "081d91921f05a8a39d39aef667eddb88e96300c7",
                                    "branch": "master",
                                    "message": "",
                                    "author": "bateslouis",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "head_totals_c": "85.00000",
                            },
                        },
                        "data_received": None,
                    },
                },
            ],
        }
        assert (
            result["notifications"][0]["result"]
            == expected_result["notifications"][0]["result"]
        )
        assert result["notifications"][0] == expected_result["notifications"][0]
        assert result["notifications"][1] == expected_result["notifications"][1]
        assert (
            result["notifications"][2]["result"]
            == expected_result["notifications"][2]["result"]
        )
        assert result["notifications"][2] == expected_result["notifications"][2]
        assert result["notifications"] == expected_result["notifications"]
        assert result == expected_result

    @patch("requests.post")
    @pytest.mark.asyncio
    async def test_simple_call_only_status_notifiers_with_pull_request(
        self,
        mock_post_request,
        dbsession,
        mocker,
        codecov_vcr,
        mock_storage,
        mock_configuration,
    ):
        mock_post_request.return_value.status_code = 200
        mock_configuration.params["setup"][
            "codecov_dashboard_url"
        ] = "https://myexamplewebsite.io"
        mocked_app = mocker.patch.object(NotifyTask, "app")
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token=sample_token,
            owner__service="github",
            owner__username="ThiagoCodecov",
            owner__service_id="44376991",
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        head_commitid = "11daa27b1b74fd181836a64106f936a16404089c"
        master_sha = "f0895290dc26668faeeb20ee5ccd4cc995925775"
        master_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid=master_sha,
            repository=repository,
            author__username="bateslouis",
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="thiago/base-no-base",
            commitid=head_commitid,
            parent_commit_id=master_commit.commitid,
            repository=repository,
            author__username="rolabuhasna",
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
            master_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt"
            )
            mock_storage.write_file("archive", master_chunks_url, content)
        result = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={
                "coverage": {
                    "status": {"project": True, "patch": True, "changes": True}
                }
            },
        )
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "status-project",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "title": "codecov/project",
                            "state": "success",
                            "message": "85.00% (+0.00%) compared to f089529",
                        },
                        "data_received": {"id": 9333363767},
                    },
                },
                {
                    "notifier": "status-patch",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "title": "codecov/patch",
                            "state": "success",
                            "message": "Coverage not affected when comparing f089529...11daa27",
                        },
                        "data_received": {"id": 9333363778},
                    },
                },
                {
                    "notifier": "status-changes",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "title": "codecov/changes",
                            "state": "success",
                            "message": "No unexpected coverage changes found",
                        },
                        "data_received": {"id": 9333363801},
                    },
                },
                {
                    "notifier": "codecov-slack-app",
                    "title": "codecov-slack-app",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": "Successfully notified slack app",
                        "data_sent": {
                            "repository": "example-python",
                            "owner": "ThiagoCodecov",
                            "comparison": {
                                "url": "https://myexamplewebsite.io/gh/ThiagoCodecov/example-python/commit/11daa27b1b74fd181836a64106f936a16404089c",
                                "message": "no change",
                                "coverage": "0.00",
                                "notation": "",
                                "head_commit": {
                                    "commitid": "11daa27b1b74fd181836a64106f936a16404089c",
                                    "branch": "thiago/base-no-base",
                                    "message": "",
                                    "author": "rolabuhasna",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "base_commit": {
                                    "commitid": "f0895290dc26668faeeb20ee5ccd4cc995925775",
                                    "branch": "master",
                                    "message": "",
                                    "author": "bateslouis",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "head_totals_c": "85.00000",
                            },
                        },
                        "data_received": None,
                    },
                },
            ],
        }
        assert result == expected_result

    @patch("requests.post")
    @pytest.mark.asyncio
    async def test_simple_call_status_and_notifiers(
        self,
        mock_post_request,
        dbsession,
        mocker,
        codecov_vcr,
        mock_storage,
        mock_configuration,
    ):
        mock_post_request.return_value.status_code = 200
        mock_configuration.params["setup"][
            "codecov_dashboard_url"
        ] = "https://myexamplewebsite.io"
        mocker.patch.object(NotifyTask, "app")
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token=sample_token,
            owner__username="test-acc9",
            owner__service="github",
            owner__service_id="104562106",
            owner__email="atest7321@gmail.com",
            name="test_example",
            image_token="abcdefghij",
        )
        dbsession.add(repository)
        dbsession.flush()
        head_commitid = "610ada9fa2bbc49f1a08917da3f73bef2d03709c"
        master_sha = "ef6edf5ae6643d53a7971fb8823d3f7b2ac65619"
        master_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid=master_sha,
            repository=repository,
            author=repository.owner,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="featureA",
            commitid=head_commitid,
            parent_commit_id=master_commit.commitid,
            repository=repository,
            author=repository.owner,
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            chunks_url = f"v4/repos/{archive_hash}/commits/{commit.commitid}/chunks.txt"
            mock_storage.write_file("archive", chunks_url, content)
            master_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt"
            )
            mock_storage.write_file("archive", master_chunks_url, content)
        result = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={
                "comment": {
                    "layout": "reach, diff, flags, files, footer",
                    "behavior": "default",
                    "require_changes": False,
                    "require_base": False,
                    "require_head": True,
                },
                "coverage": {
                    "status": {"project": True, "patch": True, "changes": True},
                    "notify": {
                        "webhook": {
                            "default": {
                                "url": "https://6da6786648c8a8e5b8b09bc6562af8b4.m.pipedream.net"
                            }
                        },
                        "slack": {
                            "default": {
                                "url": "https://hooks.slack.com/services/testkylhk/test01hg7/testohfnij1e83uy4xt8sxml"
                            }
                        },
                    },
                },
            },
        )
        expected_author_dict = {
            "username": "test-acc9",
            "service_id": repository.owner.service_id,
            "email": repository.owner.email,
            "service": "github",
            "name": repository.owner.name,
        }
        expected_result = {
            "notified": True,
            "notifications": [
                {
                    "notifier": "WebhookNotifier",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "repo": {
                                "url": "https://myexamplewebsite.io/gh/test-acc9/test_example",
                                "service_id": repository.service_id,
                                "name": "test_example",
                                "private": True,
                            },
                            "head": {
                                "author": expected_author_dict,
                                "url": "https://myexamplewebsite.io/gh/test-acc9/test_example/commit/610ada9fa2bbc49f1a08917da3f73bef2d03709c",
                                "timestamp": "2019-02-01T17:59:47",
                                "totals": {
                                    "files": 3,
                                    "lines": 20,
                                    "hits": 17,
                                    "misses": 3,
                                    "partials": 0,
                                    "coverage": "85.00000",
                                    "branches": 0,
                                    "methods": 0,
                                    "messages": 0,
                                    "sessions": 1,
                                    "complexity": 0,
                                    "complexity_total": 0,
                                    "diff": [
                                        1,
                                        2,
                                        1,
                                        1,
                                        0,
                                        "50.00000",
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                    ],
                                },
                                "commitid": head_commitid,
                                "service_url": f"https://github.com/test-acc9/test_example/commit/{head_commitid}",
                                "branch": "featureA",
                                "message": "",
                            },
                            "base": {
                                "author": expected_author_dict,
                                "url": "https://myexamplewebsite.io/gh/test-acc9/test_example/commit/ef6edf5ae6643d53a7971fb8823d3f7b2ac65619",
                                "timestamp": "2019-02-01T17:59:47",
                                "totals": {
                                    "files": 3,
                                    "lines": 20,
                                    "hits": 17,
                                    "misses": 3,
                                    "partials": 0,
                                    "coverage": "85.00000",
                                    "branches": 0,
                                    "methods": 0,
                                    "messages": 0,
                                    "sessions": 1,
                                    "complexity": 0,
                                    "complexity_total": 0,
                                    "diff": [
                                        1,
                                        2,
                                        1,
                                        1,
                                        0,
                                        "50.00000",
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                    ],
                                },
                                "commitid": "ef6edf5ae6643d53a7971fb8823d3f7b2ac65619",
                                "service_url": "https://github.com/test-acc9/test_example/commit/ef6edf5ae6643d53a7971fb8823d3f7b2ac65619",
                                "branch": "master",
                                "message": "",
                            },
                            "compare": {
                                "url": "https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1",
                                "message": "no change",
                                "coverage": Decimal("0.00"),
                                "notation": "",
                            },
                            "owner": {
                                "username": "test-acc9",
                                "service_id": repository.owner.service_id,
                                "service": "github",
                            },
                            "pull": {
                                "head": {
                                    "commit": "610ada9fa2bbc49f1a08917da3f73bef2d03709c",
                                    "branch": "master",
                                },
                                "number": "1",
                                "base": {
                                    "commit": "ef6edf5ae6643d53a7971fb8823d3f7b2ac65619",
                                    "branch": "master",
                                },
                                "open": True,
                                "id": 1,
                                "merged": False,
                            },
                        },
                        "data_received": None,
                    },
                },
                {
                    "notifier": "SlackNotifier",
                    "title": "default",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "text": f"Coverage for <https://myexamplewebsite.io/gh/test-acc9/test_example/commit/610ada9fa2bbc49f1a08917da3f73bef2d03709c|test-acc9/test_example> *no change* `<https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1|0.00%>` on `featureA` is `85.00000%` via `<https://myexamplewebsite.io/gh/test-acc9/test_example/commit/610ada9fa2bbc49f1a08917da3f73bef2d03709c|610ada9>`",
                            "author_name": "Codecov",
                            "author_link": "https://myexamplewebsite.io/gh/test-acc9/test_example/commit/610ada9fa2bbc49f1a08917da3f73bef2d03709c",
                            "attachments": [],
                        },
                        "data_received": None,
                    },
                },
                {
                    "notifier": "status-project",
                    "title": "default",
                    "result": {
                        "notification_attempted": False,
                        "notification_successful": None,
                        "explanation": "already_done",
                        "data_sent": {
                            "title": "codecov/project",
                            "state": "success",
                            "message": f"85.00% (+0.00%) compared to {master_sha[:7]}",
                        },
                        "data_received": None,
                    },
                },
                {
                    "notifier": "status-patch",
                    "title": "default",
                    "result": {
                        "notification_attempted": False,
                        "notification_successful": None,
                        "explanation": "already_done",
                        "data_sent": {
                            "title": "codecov/patch",
                            "state": "success",
                            "message": f"Coverage not affected when comparing {master_sha[:7]}...{head_commitid[:7]}",
                        },
                        "data_received": None,
                    },
                },
                {
                    "notifier": "status-changes",
                    "title": "default",
                    "result": {
                        "notification_attempted": False,
                        "notification_successful": None,
                        "explanation": "already_done",
                        "data_sent": {
                            "title": "codecov/changes",
                            "state": "success",
                            "message": "No unexpected coverage changes found",
                        },
                        "data_received": None,
                    },
                },
                {
                    "notifier": "codecov-slack-app",
                    "title": "codecov-slack-app",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": "Successfully notified slack app",
                        "data_sent": {
                            "repository": "test_example",
                            "owner": "test-acc9",
                            "comparison": {
                                "url": "https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1",
                                "message": "no change",
                                "coverage": "0.00",
                                "notation": "",
                                "head_commit": {
                                    "commitid": "610ada9fa2bbc49f1a08917da3f73bef2d03709c",
                                    "branch": "featureA",
                                    "message": "",
                                    "author": "test-acc9",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "base_commit": {
                                    "commitid": "ef6edf5ae6643d53a7971fb8823d3f7b2ac65619",
                                    "branch": "master",
                                    "message": "",
                                    "author": "test-acc9",
                                    "timestamp": "2019-02-01T17:59:47",
                                    "ci_passed": True,
                                    "totals": {
                                        "C": 0,
                                        "M": 0,
                                        "N": 0,
                                        "b": 0,
                                        "c": "85.00000",
                                        "d": 0,
                                        "diff": [
                                            1,
                                            2,
                                            1,
                                            1,
                                            0,
                                            "50.00000",
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                            0,
                                        ],
                                        "f": 3,
                                        "h": 17,
                                        "m": 3,
                                        "n": 20,
                                        "p": 0,
                                        "s": 1,
                                    },
                                    "pull": None,
                                },
                                "head_totals_c": "85.00000",
                            },
                        },
                        "data_received": None,
                    },
                },
                {
                    "notifier": "comment",
                    "title": "comment",
                    "result": {
                        "notification_attempted": True,
                        "notification_successful": True,
                        "explanation": None,
                        "data_sent": {
                            "message": [
                                "## [Codecov](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1?src=pr&el=h1) Report",
                                "> Merging [#1](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1?src=pr&el=desc) (610ada9) into [main](https://myexamplewebsite.io/gh/test-acc9/test_example/commit/ef6edf5ae6643d53a7971fb8823d3f7b2ac65619?el=desc) (ef6edf5) will **not change** coverage.",
                                "> The diff coverage is `n/a`.",
                                "",
                                "> :exclamation: Current head 610ada9 differs from pull request most recent head a2d3e3c. Consider uploading reports for the commit a2d3e3c to get more accurate results",
                                "",
                                ":exclamation: Your organization is not using the GitHub App Integration. As a result you may experience degraded service beginning May 15th. Please [install the Github App Integration](https://github.com/apps/codecov) for your organization. [Read more](https://about.codecov.io/blog/codecov-is-updating-its-github-integration/).",
                                "",
                                "[![Impacted file tree graph](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1/graphs/tree.svg?width=650&height=150&src=pr&token=abcdefghij)](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1?src=pr&el=tree)",
                                "",
                                "```diff",
                                "@@           Coverage Diff           @@",
                                "##             main       #1   +/-   ##",
                                "=======================================",
                                "  Coverage   85.00%   85.00%           ",
                                "=======================================",
                                "  Files           3        3           ",
                                "  Lines          20       20           ",
                                "=======================================",
                                "  Hits           17       17           ",
                                "  Misses          3        3           ",
                                "```",
                                "",
                                "| [Flag](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1/flags?src=pr&el=flags) | Coverage Δ | |",
                                "|---|---|---|",
                                "| [unit](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1/flags?src=pr&el=flag) | `85.00% <ø> (ø)` | |",
                                "",
                                "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more."
                                "",
                                "",
                                "",
                                "------",
                                "",
                                "[Continue to review full report in Codecov by Sentry](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1?src=pr&el=continue).",
                                "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)",
                                "> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
                                "> Powered by [Codecov](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1?src=pr&el=footer). Last update [ef6edf5...a2d3e3c](https://myexamplewebsite.io/gh/test-acc9/test_example/pull/1?src=pr&el=lastupdated). Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
                                "",
                            ],
                            "commentid": None,
                            "pullid": 1,
                        },
                        "data_received": {"id": 1203062549},
                    },
                },
            ],
        }

        pull = dbsession.query(Pull).filter_by(pullid=1, repoid=commit.repoid).first()
        assert pull.commentid == "1203062549"

        assert len(result["notifications"]) == len(expected_result["notifications"])
        for expected, actual in zip(
            sorted(result["notifications"], key=lambda x: x["notifier"]),
            sorted(expected_result["notifications"], key=lambda x: x["notifier"]),
        ):
            assert (
                expected["result"]["notification_attempted"]
                == actual["result"]["notification_attempted"]
            )
            assert (
                expected["result"]["notification_successful"]
                == actual["result"]["notification_successful"]
            )
            assert expected["result"]["explanation"] == actual["result"]["explanation"]
            assert expected["result"]["data_sent"].get("message") == actual["result"][
                "data_sent"
            ].get("message")
            assert expected["result"]["data_sent"] == actual["result"]["data_sent"]
            assert (
                expected["result"]["data_received"] == actual["result"]["data_received"]
            )
            assert expected["result"] == actual["result"]
            assert expected == actual
        assert sorted(result["notifications"], key=lambda x: x["notifier"]) == sorted(
            expected_result["notifications"], key=lambda x: x["notifier"]
        )
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_notifier_call_no_head_commit_report(
        self, dbsession, mocker, codecov_vcr, mock_storage, mock_configuration
    ):
        mock_configuration.params["setup"][
            "codecov_dashboard_url"
        ] = "https://codecov.io"
        mocked_app = mocker.patch.object(NotifyTask, "app")
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token=sample_token,
            owner__username="ThiagoCodecov",
            owner__service="github",
            owner__service_id="44376991",
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        master_commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="master",
            commitid="17a71a9a2f5335ed4d00496c7bbc6405f547a527",
            repository=repository,
        )
        commit = CommitFactory.create(
            message="",
            pullid=None,
            branch="test-branch-1",
            commitid="649eaaf2924e92dc7fd8d370ddb857033231e67a",
            repository=repository,
            _report_json=None,
        )
        dbsession.add(commit)
        dbsession.add(master_commit)
        dbsession.flush()
        task = NotifyTask()
        with open("tasks/tests/samples/sample_chunks_1.txt") as f:
            content = f.read().encode()
            archive_hash = ArchiveService.get_archive_hash(commit.repository)
            master_chunks_url = (
                f"v4/repos/{archive_hash}/commits/{master_commit.commitid}/chunks.txt"
            )
            mock_storage.write_file("archive", master_chunks_url, content)
        result = await task.run_async_within_lock(
            dbsession,
            repoid=commit.repoid,
            commitid=commit.commitid,
            current_yaml={"coverage": {"status": {"project": True}}},
        )
        expected_result = {
            "notified": False,
            "notifications": None,
            "reason": "no_head_report",
        }
        assert result == expected_result
