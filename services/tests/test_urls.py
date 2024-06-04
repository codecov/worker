from services.urls import append_tracking_params_to_urls


def test_append_tracking_params_to_urls():
    message = [
        "[This link](https://stage.codecov.io/gh/test_repo/pull/pull123?src=pr&el=h1) should be changed",
        "And [this one](https://codecov.io/bb/test_repo/pull) too, plus also [this one](codecov.io)",
        "However, [this one](https://www.xkcd.com/) should not be changed since it does not link to Codecov",
        "(Also should not replace this parenthetical non-link reference to codecov.io)",
        "Also should recognize that these are two separate URLs: [banana](https://codecov.io/pokemon)and[banana](https://codecov.io/pokemon)",
    ]

    service = "github"
    notification_type = "comment"
    org_name = "Acme Corporation"

    expected_result = [
        "[This link](https://stage.codecov.io/gh/test_repo/pull/pull123?src=pr&el=h1&utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation) should be changed",
        "And [this one](https://codecov.io/bb/test_repo/pull?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation) too, plus also [this one](codecov.io?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation)",
        "However, [this one](https://www.xkcd.com/) should not be changed since it does not link to Codecov",
        "(Also should not replace this parenthetical non-link reference to codecov.io)",
        "Also should recognize that these are two separate URLs: [banana](https://codecov.io/pokemon?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation)and[banana](https://codecov.io/pokemon?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation)",
    ]
    result = [
        append_tracking_params_to_urls(
            m, service=service, notification_type=notification_type, org_name=org_name
        )
        for m in message
    ]

    assert result == expected_result
