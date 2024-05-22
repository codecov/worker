import pytest
from shared.typings.torngit import GithubInstallationInfo

from database.models.core import GithubAppInstallation
from database.tests.factories.core import OwnerFactory
from helpers.exceptions import RequestedGithubAppNotFound
from services.bots.github_apps import get_specific_github_app_details


class TestGetSpecificGithubAppDetails(object):
    def _get_owner_with_apps(self, dbsession):
        owner = OwnerFactory(service="github")
        app_1 = GithubAppInstallation(
            owner=owner,
            installation_id=1200,
            app_id=12,
        )
        app_2 = GithubAppInstallation(
            owner=owner,
            installation_id=1500,
            app_id=15,
            pem_path="some_path",
        )
        dbsession.add_all([owner, app_1, app_2])
        dbsession.flush()
        assert owner.github_app_installations == [app_1, app_2]
        return owner

    def test_get_specific_github_app_details(self, dbsession):
        owner = self._get_owner_with_apps(dbsession)
        assert get_specific_github_app_details(
            owner, owner.github_app_installations[0].id, "commit_id_for_logs"
        ) == GithubInstallationInfo(
            id=owner.github_app_installations[0].id,
            installation_id=1200,
            app_id=12,
            pem_path=None,
        )
        assert get_specific_github_app_details(
            owner, owner.github_app_installations[1].id, "commit_id_for_logs"
        ) == GithubInstallationInfo(
            id=owner.github_app_installations[1].id,
            installation_id=1500,
            app_id=15,
            pem_path="some_path",
        )

    def test_get_specific_github_app_not_found(self, dbsession):
        owner = self._get_owner_with_apps(dbsession)
        with pytest.raises(RequestedGithubAppNotFound):
            get_specific_github_app_details(owner, 123456, "commit_id_for_logs")
