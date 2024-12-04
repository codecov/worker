import pytest

from database.tests.factories import CommitFactory, OwnerFactory
from services.yaml import save_repo_yaml_to_database_if_needed
from test_utils.base import BaseTestCase


class TestYamlSavingService(BaseTestCase):
    def test_save_repo_yaml_to_database_if_needed(self, mocker):
        commit = CommitFactory.create(
            branch="master", repository__branch="master", repository__yaml={"old_stuff"}
        )
        commit_yaml = {"new_values": "aHAAA"}
        res = save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        assert res
        assert commit.repository.yaml == commit_yaml
        assert commit.repository.branch == "master"
        assert commit.repository.bot_id is None

    @pytest.mark.django_db
    def test_save_repo_yaml_to_database_if_needed_with_new_branch_and_bot(self, mocker):
        commit = CommitFactory.create(
            branch="master",
            repository__branch="master",
            repository__service_id="github",
            repository__yaml={"old_stuff"},
        )
        bot_owner = OwnerFactory.create(name="robot", service="github")
        commit_yaml = {
            "new_values": "aHAAA",
            "codecov": {"branch": "brand_new_branch", "bot": "robot"},
        }
        res = save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        assert res
        assert commit.repository.yaml == commit_yaml
        assert commit.repository.branch == "brand_new_branch"
        assert commit.repository.bot_id == bot_owner.ownerid

    def test_save_repo_yaml_to_database_not_needed(self, mocker):
        commit = CommitFactory.create(
            branch="master",
            repository__branch="develop",
            repository__yaml={"old_stuff": "old_feelings"},
        )
        commit_yaml = {"new_values": "aHAAA"}
        res = save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        assert not res
        assert commit.repository.yaml == {"old_stuff": "old_feelings"}
