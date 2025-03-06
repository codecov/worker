import os
from datetime import datetime, timezone

import mock
import pytest
from shared.torngit.exceptions import TorngitClientError, TorngitServerUnreachableError
from shared.validation.types import CoverageCommentRequiredChanges
from shared.yaml import UserYaml

from database.tests.factories import CommitFactory
from services.yaml import get_current_yaml
from test_utils.base import BaseTestCase


class TestYamlService(BaseTestCase):
    def test_get_final_yaml_no_yaml_no_config_yaml(self, mock_configuration):
        expected_result = {}
        result = UserYaml.get_final_yaml(
            owner_yaml=None, repo_yaml=None, commit_yaml=None
        )
        assert expected_result == result.to_dict()

    def test_get_final_yaml_empty_yaml_no_config_yaml(self, mock_configuration):
        expected_result = {}
        result = UserYaml.get_final_yaml(owner_yaml={}, repo_yaml={}, commit_yaml={})
        assert expected_result == result.to_dict()

    def test_get_final_yaml_no_yaml(self, mock_configuration):
        mock_configuration.set_params(
            {
                "site": {
                    "coverage": {"precision": 2},
                    "parsers": {"javascript": {"enable_partials": True}},
                }
            }
        )
        expected_result = {
            "coverage": {"precision": 2},
            "parsers": {"javascript": {"enable_partials": True}},
        }
        result = UserYaml.get_final_yaml(owner_yaml={}, repo_yaml={}, commit_yaml={})
        assert expected_result == result.to_dict()

    def test_get_final_yaml_no_thing_set_at_all(self, mocker, mock_configuration):
        mock_configuration._params = None
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch.object(
            mock_configuration, "load_yaml_file", side_effect=FileNotFoundError()
        )
        expected_result = {
            "codecov": {"require_ci_to_pass": True, "notify": {"wait_for_ci": True}},
            "coverage": {
                "precision": 2,
                "round": "down",
                "range": [60.0, 80.0],
                "status": {
                    "project": True,
                    "patch": True,
                    "changes": False,
                    "default_rules": {"flag_coverage_not_uploaded_behavior": "include"},
                },
            },
            "comment": {
                "layout": "reach,diff,flags,tree,reach",
                "behavior": "default",
                "show_carryforward_flags": False,
            },
            "github_checks": {"annotations": True},
            "slack_app": True,
        }
        result = UserYaml.get_final_yaml(owner_yaml={}, repo_yaml={}, commit_yaml={})
        assert expected_result == result.to_dict()

    def test_get_final_yaml_owner_yaml(self, mock_configuration):
        mock_configuration.set_params(
            {
                "site": {
                    "coverage": {"precision": 2},
                    "parsers": {"javascript": {"enable_partials": True}},
                }
            }
        )
        expected_result = {
            "coverage": {"precision": 2},
            "parsers": {
                "javascript": {"enable_partials": True},
                "new_language": "damn right",
            },
        }
        result = UserYaml.get_final_yaml(
            owner_yaml={"parsers": {"new_language": "damn right"}},
            repo_yaml={},
            commit_yaml={},
        )
        assert expected_result == result.to_dict()

    def test_get_final_yaml_both_repo_and_commit_yaml(self, mock_configuration):
        mock_configuration.set_params(
            {
                "site": {
                    "coverage": {"precision": 2},
                    "parsers": {"javascript": {"enable_partials": True}},
                }
            }
        )
        expected_result = {
            "coverage": {"precision": 2},
            "parsers": {
                "javascript": {"enable_partials": True},
                "different_language": "say what",
            },
        }
        result = UserYaml.get_final_yaml(
            owner_yaml=None,
            repo_yaml={"parsers": {"new_language": "damn right"}},
            commit_yaml={"parsers": {"different_language": "say what"}},
        )
        assert expected_result == result.to_dict()

    @pytest.mark.asyncio
    async def test_get_current_yaml(self, mocker, mock_configuration):
        mock_configuration.set_params(
            {
                "site": {
                    "comment": {
                        "behavior": "default",
                        "layout": "header, diff",
                        "require_changes": [
                            CoverageCommentRequiredChanges.no_requirements.value
                        ],
                    }
                }
            }
        )
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
        sample_yaml = "\n".join(
            ["codecov:", "  notify:", "    require_ci_to_pass: yes"]
        )
        contents_result = {"content": sample_yaml}
        contents_result_future = contents_result
        valid_handler = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(return_value=list_files_future),
            get_source=mock.AsyncMock(return_value=contents_result_future),
        )
        commit = CommitFactory.create(
            repository__yaml={
                "coverage": {
                    "precision": 2,
                    "round": "down",
                    "range": [70.0, 100.0],
                    "status": {"project": True, "patch": True, "changes": False},
                }
            }
        )
        res = await get_current_yaml(commit, valid_handler)
        assert res.to_dict() == {
            "codecov": {"notify": {}, "require_ci_to_pass": True},
            "comment": {
                "behavior": "default",
                "layout": "header, diff",
                "require_changes": [
                    CoverageCommentRequiredChanges.no_requirements.value
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_get_current_yaml_with_owner_yaml(self, mocker, mock_configuration):
        mock_configuration.set_params(
            {
                "site": {
                    "comment": {
                        "behavior": "default",
                        "layout": "header, diff",
                        "require_changes": [
                            CoverageCommentRequiredChanges.no_requirements.value
                        ],
                    }
                }
            }
        )
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
        sample_yaml = "\n".join(
            ["codecov:", "  notify:", "    require_ci_to_pass: yes"]
        )
        contents_result = {"content": sample_yaml}
        contents_result_future = contents_result
        valid_handler = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(return_value=list_files_future),
            get_source=mock.AsyncMock(return_value=contents_result_future),
        )
        commit = CommitFactory.create(
            repository__yaml={
                "coverage": {
                    "precision": 2,
                    "round": "down",
                    "range": [70.0, 100.0],
                    "status": {"project": True, "patch": True, "changes": False},
                }
            },
            repository__owner__yaml={"codecov": {"bot": "ThiagoCodecov"}},
        )
        res = await get_current_yaml(commit, valid_handler)
        assert res.to_dict() == {
            "codecov": {
                "bot": "ThiagoCodecov",
                "notify": {},
                "require_ci_to_pass": True,
            },
            "comment": {
                "behavior": "default",
                "layout": "header, diff",
                "require_changes": [
                    CoverageCommentRequiredChanges.no_requirements.value
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_get_current_yaml_invalid_yaml(
        self, mocker, dbsession, mock_configuration
    ):
        mock_configuration.set_params(
            {
                "site": {
                    "comment": {
                        "behavior": "default",
                        "layout": "header, diff",
                        "require_changes": [
                            CoverageCommentRequiredChanges.no_requirements.value
                        ],
                    }
                }
            }
        )
        mocked_list_files_result = [
            {"name": "codecov.yaml", "path": "codecov.yaml", "type": "file"}
        ]
        list_files_future = mocked_list_files_result
        sample_yaml = "\n".join(
            ["@codecov:", "  notify:", "    require_ci_to_pass: yes"]
        )
        contents_result = {"content": sample_yaml}
        contents_result_future = contents_result
        valid_handler = mocker.MagicMock(
            list_top_level_files=mock.AsyncMock(return_value=list_files_future),
            get_source=mock.AsyncMock(return_value=contents_result_future),
        )
        commit = CommitFactory.create(
            # Setting the time to _before_ patch centric default YAMLs start date of 2024-04-30
            repository__owner__createstamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
            repository__yaml={
                "coverage": {
                    "precision": 2,
                    "round": "down",
                    "range": [70.0, 100.0],
                    "status": {"project": True, "patch": True, "changes": False},
                }
            },
        )

        dbsession.add(commit)

        res = await get_current_yaml(commit, valid_handler)
        assert res.to_dict() == {
            "coverage": {
                "precision": 2,
                "round": "down",
                "range": [70.0, 100.0],
                "status": {"project": True, "patch": True, "changes": False},
            },
            "comment": {
                "behavior": "default",
                "layout": "header, diff",
                "require_changes": [
                    CoverageCommentRequiredChanges.no_requirements.value
                ],
            },
        }

        assert commit.errors[0].error_code == "invalid_yaml"
        assert len(commit.errors) == 1

    @pytest.mark.asyncio
    async def test_get_current_yaml_no_permissions(
        self, mocker, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "site": {
                    "comment": {
                        "behavior": "default",
                        "layout": "header, diff",
                        "require_changes": [
                            CoverageCommentRequiredChanges.no_requirements.value
                        ],
                    }
                }
            }
        )
        valid_handler = mocker.MagicMock(
            list_top_level_files=mocker.MagicMock(
                side_effect=TorngitClientError(404, "response", "message")
            )
        )
        commit = CommitFactory.create(
            # Setting the time to _before_ patch centric default YAMLs start date of 2024-04-30
            repository__owner__createstamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
            repository__yaml={
                "coverage": {
                    "precision": 2,
                    "round": "down",
                    "range": [70.0, 100.0],
                    "status": {"project": True, "patch": True, "changes": False},
                }
            },
        )
        dbsession.add(commit)
        res = await get_current_yaml(commit, valid_handler)
        assert res.to_dict() == {
            "coverage": {
                "precision": 2,
                "round": "down",
                "range": [70.0, 100.0],
                "status": {"project": True, "patch": True, "changes": False},
            },
            "comment": {
                "behavior": "default",
                "layout": "header, diff",
                "require_changes": [
                    CoverageCommentRequiredChanges.no_requirements.value
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_get_current_yaml_unreachable_provider(
        self, mocker, mock_configuration, dbsession
    ):
        mock_configuration.set_params(
            {
                "site": {
                    "comment": {
                        "behavior": "default",
                        "layout": "header, diff",
                        "require_changes": [
                            CoverageCommentRequiredChanges.no_requirements.value
                        ],
                    }
                }
            }
        )
        valid_handler = mocker.MagicMock(
            list_top_level_files=mocker.MagicMock(
                side_effect=TorngitServerUnreachableError()
            )
        )
        commit = CommitFactory.create(
            # Setting the time to _before_ patch centric default YAMLs start date of 2024-04-30
            repository__owner__createstamp=datetime(2023, 1, 1, tzinfo=timezone.utc),
            repository__yaml={
                "coverage": {
                    "precision": 2,
                    "round": "down",
                    "range": [70.0, 100.0],
                    "status": {"project": True, "patch": True, "changes": False},
                }
            },
        )
        dbsession.add(commit)
        res = await get_current_yaml(commit, valid_handler)
        assert res.to_dict() == {
            "coverage": {
                "precision": 2,
                "round": "down",
                "range": [70.0, 100.0],
                "status": {"project": True, "patch": True, "changes": False},
            },
            "comment": {
                "behavior": "default",
                "layout": "header, diff",
                "require_changes": [
                    CoverageCommentRequiredChanges.no_requirements.value
                ],
            },
        }
