import pytest
import mock

from tests.base import BaseTestCase
from database.tests.factories import CommitFactory
from services.yaml.fetcher import fetch_commit_yaml_from_provider


sample_yaml = """
codecov:
  notify:
    require_ci_to_pass: yes
"""

sample_yaml_with_secret = """
coverage:
  precision: 2  # 2 = xx.xx%, 0 = xx%
  round: down # default down
  range: 50...60 # default 70...90. red...green

  notify:

    slack:
      default:
        url: "secret:c/nCgqn5v1HY5VFIs9i4W3UY6eleB2rTBdBKK/ilhPR7Ch4N0FE1aO6SRfAxp3Zlm4tLNusaPY7ettH6dTYj/YhiRohxiNqJMJ4L9YQmESo="
        threshold: 1%
        branches: null  # all branches by default
        message: "Coverage {{changed}} for {{owner}}/{{repo}}"  # customize the message
        attachments: "sunburst, diff"
        only_pulls: false
        flags: null
        paths: null
"""


class TestYamlSavingService(BaseTestCase):
    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_from_provider(self, mocker):
        mocked_list_files_result = [
            {"name": ".gitignore", "path": ".gitignore", "type": "file"},
            {"name": ".travis.yml", "path": ".travis.yml", "type": "file"},
            {"name": "README.rst", "path": "README.rst", "type": "file"},
            {"name": "awesome", "path": "awesome", "type": "folder"},
            {"name": "codecov", "path": "codecov", "type": "file"},
            {"name": "codecov.yaml", "path": "codecov.yaml", "type": "file"},
            {"name": "tests", "path": "tests", "type": "folder"},
        ]
        list_files_future = mocked_list_files_result
        contents_result = {"content": sample_yaml}
        contents_result_future = contents_result
        valid_handler = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(return_value=list_files_future),
            get_source=mock.AsyncMock(return_value=contents_result_future),
        )
        commit = CommitFactory.create()
        res = await fetch_commit_yaml_from_provider(commit, valid_handler)
        assert res == {"codecov": {"notify": {}, "require_ci_to_pass": True}}
        valid_handler.list_top_level_files.assert_called_with(commit.commitid)
        valid_handler.get_source.assert_called_with("codecov.yaml", commit.commitid)

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_from_provider_with_secret(self, mocker, dbsession):
        mocked_list_files_result = [
            {"name": ".gitignore", "path": ".gitignore", "type": "file"},
            {"name": ".travis.yml", "path": ".travis.yml", "type": "file"},
            {"name": "README.rst", "path": "README.rst", "type": "file"},
            {"name": "awesome", "path": "awesome", "type": "folder"},
            {"name": "codecov", "path": "codecov", "type": "file"},
            {"name": "codecov.yaml", "path": "codecov.yaml", "type": "file"},
            {"name": "tests", "path": "tests", "type": "folder"},
        ]
        list_files_future = mocked_list_files_result
        contents_result = {"content": sample_yaml_with_secret}
        contents_result_future = contents_result
        valid_handler = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(return_value=list_files_future),
            get_source=mock.AsyncMock(return_value=contents_result_future),
        )
        good_commit = CommitFactory.create(
            repository__owner__service="github",
            repository__owner__service_id=44376991,
            repository__service_id=156617777,
        )
        dbsession.add(good_commit)
        res = await fetch_commit_yaml_from_provider(good_commit, valid_handler)
        assert res == {
            "coverage": {
                "precision": 2,
                "round": "down",
                "range": [50.0, 60.0],
                "notify": {
                    "slack": {
                        "default": {
                            "url": "http://test.thiago.website",
                            "threshold": 1.0,
                            "branches": None,
                            "message": "Coverage {{changed}} for {{owner}}/{{repo}}",
                            "attachments": "sunburst, diff",
                            "only_pulls": False,
                            "flags": None,
                            "paths": None,
                        }
                    }
                },
            }
        }
        valid_handler.list_top_level_files.assert_called_with(good_commit.commitid)
        valid_handler.get_source.assert_called_with(
            "codecov.yaml", good_commit.commitid
        )

    @pytest.mark.asyncio
    async def test_fetch_commit_yaml_from_provider_with_secret_bad_commit(
        self, mocker, dbsession
    ):
        mocked_list_files_result = [
            {"name": ".gitignore", "path": ".gitignore", "type": "file"},
            {"name": ".travis.yml", "path": ".travis.yml", "type": "file"},
            {"name": "README.rst", "path": "README.rst", "type": "file"},
            {"name": "awesome", "path": "awesome", "type": "folder"},
            {"name": "codecov", "path": "codecov", "type": "file"},
            {"name": "codecov.yaml", "path": "codecov.yaml", "type": "file"},
            {"name": "tests", "path": "tests", "type": "folder"},
        ]
        list_files_future = mocked_list_files_result
        contents_result = {"content": sample_yaml_with_secret}
        contents_result_future = contents_result
        valid_handler = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(return_value=list_files_future),
            get_source=mock.AsyncMock(return_value=contents_result_future),
        )
        bad_commit = CommitFactory.create(
            repository__owner__service="github",
            repository__owner__service_id=44123999,  # correct one is 44376991
            repository__service_id=156617777,
        )
        dbsession.add(bad_commit)
        res = await fetch_commit_yaml_from_provider(bad_commit, valid_handler)
        assert res == {
            "coverage": {
                "precision": 2,
                "round": "down",
                "range": [50.0, 60.0],
                "notify": {
                    "slack": {
                        "default": {
                            "url": "secret:c/nCgqn5v1HY5VFIs9i4W3UY6eleB2rTBdBKK/ilhPR7Ch4N0FE1aO6SRfAxp3Zlm4tLNusaPY7ettH6dTYj/YhiRohxiNqJMJ4L9YQmESo=",
                            "threshold": 1.0,
                            "branches": None,
                            "message": "Coverage {{changed}} for {{owner}}/{{repo}}",
                            "attachments": "sunburst, diff",
                            "only_pulls": False,
                            "flags": None,
                            "paths": None,
                        }
                    }
                },
            }
        }
        valid_handler.list_top_level_files.assert_called_with(bad_commit.commitid)
        valid_handler.get_source.assert_called_with("codecov.yaml", bad_commit.commitid)
