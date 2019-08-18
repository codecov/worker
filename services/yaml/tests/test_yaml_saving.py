from tests.base import BaseTestCase
from services.yaml import save_repo_yaml_to_database_if_needed
from database.tests.factories import CommitFactory


class TestYamlSavingService(BaseTestCase):

    def test_save_repo_yaml_to_database_if_needed(self, mocker):
        commit = CommitFactory.create(
            branch='master',
            repository__branch='master',
            repository__yaml={'old_stuff'}
        )
        commit_yaml = {'new_values': 'aHAAA'}
        res = save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        assert res
        assert commit.repository.yaml == commit_yaml
        assert commit.repository.branch == 'master'

    def test_save_repo_yaml_to_database_if_needed_with_new_branch(self, mocker):
        commit = CommitFactory.create(
            branch='master',
            repository__branch='master',
            repository__yaml={'old_stuff'}
        )
        commit_yaml = {'new_values': 'aHAAA', 'codecov': {'branch': 'brand_new_branch'}}
        res = save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        assert res
        assert commit.repository.yaml == commit_yaml
        assert commit.repository.branch == 'brand_new_branch'

    def test_save_repo_yaml_to_database_not_needed(self, mocker):
        commit = CommitFactory.create(
            branch='master',
            repository__branch='develop',
            repository__yaml={'old_stuff': 'old_feelings'}
        )
        commit_yaml = {'new_values': 'aHAAA'}
        res = save_repo_yaml_to_database_if_needed(commit, commit_yaml)
        assert not res
        assert commit.repository.yaml == {'old_stuff': 'old_feelings'}
