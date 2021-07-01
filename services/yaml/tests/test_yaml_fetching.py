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
