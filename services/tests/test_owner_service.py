from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
)
from database.tests.factories import OwnerFactory
from services.owner import get_owner_provider_service


class TestOwnerServiceTestCase(object):
    def test_get_owner_provider_service(self, dbsession):
        owner = OwnerFactory.create(
            service="github",
            unencrypted_oauth_token="bcaa0dc0c66b4a8c8c65ac919a1a91aa",
            bot=None,
        )
        dbsession.add(owner)
        dbsession.flush()
        res = get_owner_provider_service(owner)
        expected_data = {
            "owner": {
                "ownerid": owner.ownerid,
                "service_id": owner.service_id,
                "username": owner.username,
            },
            "repo": {},
            "installation": None,
            "fallback_installations": None,
        }
        assert res.service == "github"
        assert res.data == expected_data
        assert res.token == {"key": "bcaa0dc0c66b4a8c8c65ac919a1a91aa", "secret": None}

    def test_get_owner_provider_service_with_installation(self, dbsession, mocker):
        mocker.patch(
            "shared.bots.github_apps.get_github_integration_token",
            return_value="integration_token",
        )
        owner = OwnerFactory.create(
            service="github",
            unencrypted_oauth_token="bcaa0dc0c66b4a8c8c65ac919a1a91aa",
            bot=None,
        )
        dbsession.add(owner)
        installation = GithubAppInstallation(
            name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            installation_id=1500,
            repository_service_ids=None,
            owner=owner,
        )
        dbsession.add(installation)
        dbsession.flush()
        res = get_owner_provider_service(owner)
        expected_data = {
            "owner": {
                "ownerid": owner.ownerid,
                "service_id": owner.service_id,
                "username": owner.username,
            },
            "repo": {},
            "installation": {
                "id": installation.id,
                "installation_id": 1500,
                "pem_path": None,
                "app_id": None,
            },
            "fallback_installations": [],
        }
        assert res.service == "github"
        assert res.data == expected_data
        assert res.token == {"key": "integration_token"}

    def test_get_owner_provider_service_other_service(self, dbsession):
        owner = OwnerFactory.create(
            service="gitlab", unencrypted_oauth_token="testenll80qbqhofao65", bot=None
        )
        dbsession.add(owner)
        dbsession.flush()
        res = get_owner_provider_service(owner)
        expected_data = {
            "owner": {
                "ownerid": owner.ownerid,
                "service_id": owner.service_id,
                "username": owner.username,
            },
            "repo": {},
            "installation": None,
            "fallback_installations": None,
        }
        assert res.service == "gitlab"
        assert res.data == expected_data
        assert res.token == {"key": "testenll80qbqhofao65", "secret": None}

    def test_get_owner_provider_service_different_bot(self, dbsession):
        bot_token = "bcaa0dc0c66b4a8c8c65ac919a1a91aa"
        owner = OwnerFactory.create(
            unencrypted_oauth_token="testyftq3ovzkb3zmt823u3t04lkrt9w",
            bot=OwnerFactory.create(unencrypted_oauth_token=bot_token),
        )
        dbsession.add(owner)
        dbsession.flush()
        res = get_owner_provider_service(owner, ignore_installation=True)
        expected_data = {
            "owner": {
                "ownerid": owner.ownerid,
                "service_id": owner.service_id,
                "username": owner.username,
            },
            "repo": {},
            "installation": None,
            "fallback_installations": None,
        }
        assert res.data["repo"] == expected_data["repo"]
        assert res.data == expected_data
        assert res.token == {"key": bot_token, "secret": None}
