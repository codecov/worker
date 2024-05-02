import pytest

from database.tests.factories import RepositoryFactory
from services.repository import (
    get_repo_provider_service,
)


class TestRepositoryServiceIntegration(object):
    @pytest.mark.asyncio
    async def test_get_repo_provider_service_github(self, dbsession, codecov_vcr):
        repo = RepositoryFactory.create(
            owner__unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            owner__username="ThiagoCodecov",
            owner__service="github",
            name="example-python",
        )
        dbsession.add(repo)
        dbsession.flush()
        service = get_repo_provider_service(repo)
        expected_result = {
            "author": {
                "id": None,
                "username": None,
                "email": "jerrod@fundersclub.com",
                "name": "Jerrod",
            },
            "message": "Adding 'include' term if multiple sources\n\nbased on a support ticket around multiple sources\r\n\r\nhttps://codecov.freshdesk.com/a/tickets/87",
            "parents": ["adb252173d2107fad86bcdcbc149884c2dd4c609"],
            "commitid": "6895b64",
            "timestamp": "2018-07-09T23:39:20Z",
        }

        commit = await service.get_commit("6895b64")
        assert commit["author"] == expected_result["author"]
        assert commit == expected_result

    @pytest.mark.asyncio
    async def test_get_repo_provider_service_bitbucket(
        self, dbsession, mock_configuration, codecov_vcr
    ):
        mock_configuration.params["bitbucket"] = {
            "client_id": "testzdcviyi3x7f8h0",
            "client_secret": "testw35rwjj75gbaervbsmgl13vf39jd",
        }
        repo = RepositoryFactory.create(
            owner__unencrypted_oauth_token="H6scSkq7rKZDXtDqe4:kdTf3NVM9RkUc9rAaDM853j5f32PkBGU",
            owner__username="ThiagoCodecov",
            owner__service="bitbucket",
            name="example-python",
        )
        dbsession.add(repo)
        dbsession.flush()
        service = get_repo_provider_service(repo)
        commit = await service.get_commit("6895b64")
        expected_result = {
            "author": {
                "id": None,
                "username": None,
                "email": "jerrod@fundersclub.com",
                "name": "Jerrod",
            },
            "message": "Adding 'include' term if multiple sources\n\nbased on a support ticket around multiple sources\r\n\r\nhttps://codecov.freshdesk.com/a/tickets/87",
            "parents": ["adb252173d2107fad86bcdcbc149884c2dd4c609"],
            "commitid": "6895b64",
            "timestamp": "2018-07-09T23:39:20+00:00",
        }
        assert commit["author"] == expected_result["author"]
        assert commit == expected_result

    @pytest.mark.asyncio
    async def test_get_repo_provider_service_gitlab(
        self, dbsession, mock_configuration, codecov_vcr
    ):
        mock_configuration.params["bitbucket"] = {
            "client_id": "testzdcviyi3x7f8h0",
            "client_secret": "testw35rwjj75gbaervbsmgl13vf39jd",
        }
        repo = RepositoryFactory.create(
            owner__unencrypted_oauth_token="test10r65j3084oje16v12yzfuojw4yovzwa18y9txooo716odibjdwk8cn1p42r",
            owner__username="stevepeak",
            owner__service="gitlab",
            name="example-python",
            service_id="187725",
        )
        dbsession.add(repo)
        dbsession.flush()
        service = get_repo_provider_service(repo)
        commit = await service.get_commit("0028015f7fa260f5fd68f78c0deffc15183d955e")
        expected_result = {
            "author": {
                "id": None,
                "username": None,
                "email": "steve@stevepeak.net",
                "name": "stevepeak",
            },
            "message": "added large file\n",
            "parents": ["5716de23b27020419d1a40dd93b469c041a1eeef"],
            "commitid": "0028015f7fa260f5fd68f78c0deffc15183d955e",
            "timestamp": "2014-10-19T14:32:33.000Z",
        }
        assert commit["author"] == expected_result["author"]
        assert commit == expected_result
