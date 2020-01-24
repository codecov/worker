import pytest

from database.tests.factories import OwnerFactory
from tasks.ghm_sync_plans import SyncPlansTask

fake_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0szMfBZ4kn9q+puMA5YETxdjj/claRhyCQXZGLXzxI8eY5OQ
2CXpa27got7wh05xRnstaH4LEvlRo50kwKdM4bNRumCT8tZXSGe+2H76WNP+ePrP
mdYhrtld2FpKh6ssK1lgw1dxZR5eezV+7z+BzBATqjFqYvSENXpEnZ16QKNLWtOJ
55EzKVgFQ+012Zf/RF111Xs0t2VRpMHIdsZ8+2EmAw44d9UonvYPvFoUD+HscIab
RW4s4S1Sn/RFL2AkwD9Urn8XSeclHd7AoOfUm2ssngHdqon6Ko55ETDw1lOXpw3a
S9+7lJJ+9OP8nd2nvn9xetyFgMvuJhqXpR7auQIDAQABAoIBAG+jbpg4/ln3iRx3
zEsJ4/ZPGLdh2Do0bBBDPJpNom/yq9FokUknqtruuaEIGLJP5MXC7mVse0jtKUNR
MemlsJ3Hbf0asL/mrAr4hqX5eXQZsac4jUGXmfcTvxOZnecDzDyY9Rn+8VrwHnF5
/2ONapw7125HBWSqwmnf+v7OK7SWz89K4dBAfbExssmmBAyHMVpAA3qBAONNE5xr
voEp7oiulaR44su2hOoQmmcPh5QfENv+ps4HnGMPGoZZ2HpXcubWgNrHJt+qDUR3
2fG/LezTQrcQO2M/CCqa8RGfWr20UBWxHvE6avoiE0tuorBy8YAk/FwfUNfJR4g/
75GlHxECgYEA+lLYjAIdmw4rGxEdh51J33sAhd8jPbdEp6EGJQjZEJVj47HERGL7
uAML6y/xpZKGfRg4/2VhYwvQo1CY4xXekCPyVEA/cEos2CP5iAaT+N8BeNaBlq/2
ZTELlPpJmIu+9sqQZVC6Js8aojPcNCYPFUPzhQ4FszEZYfLQhAjMzp8CgYEA15SD
pJEVq74vguH+7q51f0cvOVkO3DWSs8xy1QwXYRveaTW203JGzc48bIn5c0WTkoyd
uBrVCfQyXYuwPkgA/vuG6zzjvMf1rxXiwSlpA74ObChePezW8TgnQZTKhHq8prAq
0EbA8aTFU9FzEiT6qktpV4scphAhuJdtbEGfT6cCgYBFgT1ZWrkHtZ5obI8reZPq
dofFpBhv6XQpqz8+hz9mKGTM8y4Q4v8Lr+TeT7ikBZRMJa6l02uACebLgfSBkS/0
C9ccZ551ulLLTOnbSCBMCPeqqrzer0sV+9FAc2J99cd3VPVU/F5Dqlu1z/qDjFHB
0NVMC4GvqKFonfghwSPE9wKBgF9u62fqokFJDBdQnF5k9LbHeGxWtHFfdfYKR7tw
gtkGUUsZ8DlimV16Mt2JptgUsONrRFa/6hdh9vnaYMbxcR9vkaaJafekPWqosZz5
C/gQJqpSpIWdVvmp9hbeG1jSTLktu4ZADCHs4z3btqkNnbnNcHDEsIYDFip1Podx
9Wh5AoGBAO14GjlVcMMvrjB1Aitn9YZqQCt3owecvvYpKhZyQP5f/7bjQV0WgWpX
QGmaM7pFvAq0mxD8ocVdH/AC22U1L77re9V3h/AXCZjmOiouo+rrO8cj6tO6/AtA
Du117djXnAUavnjRWM27JncX5DW6x+FWl/WfHKfSUife5QZdNz+a
-----END RSA PRIVATE KEY-----
"""


@pytest.mark.integration
class TestGHMarketplaceSyncPlansTask(object):
    @pytest.mark.asyncio
    async def test_purchase(self, dbsession, mocker, mock_configuration, codecov_vcr):
        mock_configuration.loaded_files[
            ("github", "integration", "pem")
        ] = fake_private_key

        mock_configuration.params["github"] = {
            "integration": {
                "pem": "/home/src/certs/github.pem",
                "id": 51984,  # Fake integration id, tested with a real one
            }
        }
        mock_configuration.params["services"]["github_marketplace"] = dict(
            use_stubbed=True
        )

        owner = OwnerFactory.create(
            username="cc-test",
            service="github",
            service_id="3877742",
            plan=None,
            plan_provider=None,
            plan_auto_activate=None,
            plan_user_count=None,
        )
        dbsession.add(owner)
        dbsession.flush()

        sender = {
            "login": "cc-test",
            "id": 3877742,
        }
        account = {
            "type": "Organization",
            "id": 8226205,
            "login": "codecov",
            "organization_billing_email": "hello@codecov.io",
        }
        action = "purchased"

        task = SyncPlansTask()
        await task.run_async(dbsession, sender=sender, account=account, action=action)

        assert owner.plan == "users"
        assert owner.plan_provider == "github"
        assert owner.plan_auto_activate is True
        assert owner.plan_user_count == 10
