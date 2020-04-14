import os

from helpers.sentry import initialize_sentry, before_send


class TestSentry(object):
    def test_initialize_sentry(self, mocker, mock_configuration):
        mock_configuration._params["services"] = {"sentry": {"server_dsn": "this_dsn"}}
        mocker.patch.dict(os.environ, {"RELEASE_VERSION": "FAKE_VERSION_FOR_YOU"})
        mocked_init = mocker.patch("helpers.sentry.sentry_sdk.init")
        assert initialize_sentry() is None
        mocked_init.assert_called_with(
            "this_dsn",
            before_send=before_send,
            release="worker-FAKE_VERSION_FOR_YOU",
            sample_rate=1.0,
            integrations=[mocker.ANY, mocker.ANY, mocker.ANY]
        )
