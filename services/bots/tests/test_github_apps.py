import datetime

import pytest
from shared.typings.torngit import GithubInstallationInfo

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories.core import OwnerFactory
from helpers.exceptions import NoConfiguredAppsAvailable, RequestedGithubAppNotFound
from services.bots.github_apps import (
    get_github_app_info_for_owner,
    get_specific_github_app_details,
)


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

    @pytest.mark.parametrize(
        "app, is_rate_limited",
        [
            pytest.param(
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1400,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=400,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                    is_suspended=True,
                ),
                False,
                id="suspended_app",
            ),
            pytest.param(
                GithubAppInstallation(
                    repository_service_ids=None,
                    installation_id=1400,
                    name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
                    app_id=400,
                    pem_path="pem_path",
                    created_at=datetime.datetime.now(datetime.UTC),
                    is_suspended=False,
                ),
                True,
                id="rate_limited_app",
            ),
        ],
    )
    def test_raise_NoAppsConfiguredAvailable_if_suspended_or_rate_limited(
        self, app, is_rate_limited, mocker, dbsession
    ):
        owner = OwnerFactory(
            service="github",
            bot=None,
            unencrypted_oauth_token="owner_token: :refresh_token",
        )
        dbsession.add(owner)

        app.owner = owner
        dbsession.add(app)
        dbsession.flush()

        mock_is_rate_limited = mocker.patch(
            "services.bots.github_apps.is_installation_rate_limited",
            return_value=is_rate_limited,
        )
        with pytest.raises(NoConfiguredAppsAvailable):
            get_github_app_info_for_owner(owner)
        mock_is_rate_limited.assert_called()
