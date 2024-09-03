from unittest.mock import MagicMock

import pytest
from shared.validation.types import BundleThreshold
from shared.yaml import UserYaml

from database.models.core import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    GithubAppInstallation,
    Owner,
)
from database.tests.factories.core import OwnerFactory
from services.bundle_analysis.notify.helpers import (
    bytes_readable,
    get_github_app_used,
    get_notification_types_configured,
    is_bundle_change_within_bundle_threshold,
    to_BundleThreshold,
)
from services.bundle_analysis.notify.types import NotificationType


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
            (NotificationType.PR_COMMENT, NotificationType.COMMIT_STATUS),
            id="default_values_github_no_apps",
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": False}},
            "github_owner_with_apps",
            (NotificationType.PR_COMMENT, NotificationType.GITHUB_COMMIT_CHECK),
            id="default_values_github_with_apps",
        ),
        pytest.param(
            {"comment": {"require_bundle_changes": False}},
            "gitlab_owner",
            (NotificationType.PR_COMMENT, NotificationType.COMMIT_STATUS),
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


@pytest.mark.parametrize(
    "torngit, expected",
    [
        pytest.param(None, None, id="no_torngit"),
        pytest.param(
            MagicMock(data={"installation": None}), None, id="torngit_no_installation"
        ),
        pytest.param(
            MagicMock(data={"installation": {"id": 12}}),
            12,
            id="torngit_with_installation",
        ),
    ],
)
def test_get_github_app_used(torngit, expected):
    assert get_github_app_used(torngit) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (100, BundleThreshold("absolute", 100)),
        (0, BundleThreshold("absolute", 0)),
        (14.5, BundleThreshold("percentage", 14.5)),
        (["percentage", 14.5], BundleThreshold("percentage", 14.5)),
        (["absolute", 1000], BundleThreshold("absolute", 1000)),
        (BundleThreshold("absolute", 1000), BundleThreshold("absolute", 1000)),
        (("absolute", 1000), BundleThreshold("absolute", 1000)),
    ],
)
def test_to_BundleThreshold(value, expected):
    assert to_BundleThreshold(value) == expected


@pytest.mark.parametrize("value", ["value", [1, 2, 3], None])
def test_to_BundleThreshold_raises(value):
    with pytest.raises(TypeError):
        to_BundleThreshold(value)


@pytest.mark.parametrize(
    "threshold, expected",
    [
        (BundleThreshold("absolute", 10001), True),
        (BundleThreshold("absolute", 10000), True),
        (BundleThreshold("absolute", 9999), False),
        (BundleThreshold("percentage", 13.0), True),
        (BundleThreshold("percentage", 12.5), True),
        (BundleThreshold("percentage", 12.0), False),
    ],
)
def test_is_bundle_change_within_bundle_threshold(threshold, expected):
    comparison = MagicMock(
        name="fake_comparison", total_size_delta=10000, percentage_delta=12.5
    )
    assert comparison.total_size_delta == 10000
    assert is_bundle_change_within_bundle_threshold(comparison, threshold) == expected
