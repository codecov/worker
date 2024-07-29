import pytest
from shared.yaml import UserYaml

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Owner,
)
from database.tests.factories.core import OwnerFactory
from services.bundle_analysis.new_notify.helpers import (
    bytes_readable,
    get_notification_types_configured,
)
from services.bundle_analysis.new_notify.types import NotificationType


@pytest.mark.parametrize(
    "input, expected",
    [
        pytest.param(0, "0 bytes"),
        pytest.param(123, "123 bytes"),
        pytest.param(1000, "1.0kB"),
        pytest.param(1500, "1.5kB"),
        pytest.param(1000000, "1.0MB"),
        pytest.param(1500010, "1.5MB"),
        pytest.param(1e9, "1.0GB"),
        pytest.param(1230000000, "1.23GB"),
    ],
)
def test_bytes_readable(input, expected):
    assert bytes_readable(input) == expected


@pytest.fixture
def github_owner_no_apps(dbsession) -> Owner:
    owner = OwnerFactory(service="github")
    dbsession.add(owner)
    dbsession.commit()
    assert owner.github_app_installations == []
    return owner


@pytest.fixture
def github_owner_with_apps(dbsession) -> Owner:
    owner = OwnerFactory(service="github")
    ghapp = GithubAppInstallation(
        ownerid=owner.ownerid,
        owner=owner,
        name=GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    )
    dbsession.add_all([owner, ghapp])
    dbsession.commit()
    assert owner.github_app_installations == [ghapp]
    return owner


@pytest.fixture
def gitlab_owner(dbsession) -> Owner:
    owner = OwnerFactory(service="gitlab")
    dbsession.add(owner)
    dbsession.commit()
    return owner


@pytest.mark.parametrize(
    "config, owner_fixture, expected",
    [
        pytest.param(
            {"comment": False, "bundle_analysis": {"status": False}},
            "github_owner_no_apps",
            (),
            id="no_notification_configured",
        ),
        # The default site configuration puts the `comment` as a dict
        pytest.param(
            {"comment": {"require_bundle_changes": False}},
            "github_owner_no_apps",
            (NotificationType.COMMIT_STATUS, NotificationType.PR_COMMENT),
            id="default_values_github_no_apps",
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": False}},
            "github_owner_with_apps",
            (NotificationType.GITHUB_COMMIT_CHECK, NotificationType.PR_COMMENT),
            id="default_values_github_with_apps",
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": False}},
            "gitlab_owner",
            (NotificationType.COMMIT_STATUS, NotificationType.PR_COMMENT),
            id="default_values_gitlab",
        ),
        pytest.param(
            {"comment": False, "bundle_analysis": {"status": True}},
            "gitlab_owner",
            (NotificationType.COMMIT_STATUS,),
            id="just_commit_status",
        ),
        pytest.param(
            {
                "comment": {"require_bundle_changes": False},
                "bundle_analysis": {"status": False},
            },
            "gitlab_owner",
            (NotificationType.PR_COMMENT,),
            id="just_pr_comment",
        ),
    ],
)
def test_get_configuration_types_configured(config, owner_fixture, expected, request):
    owner = request.getfixturevalue(owner_fixture)
    yaml = UserYaml.from_dict(config)
    assert get_notification_types_configured(yaml, owner) == expected
