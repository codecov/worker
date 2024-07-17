from typing import Any

import pytest
from pytest import LogCaptureFixture
from pytest_mock import MockFixture
from shared.django_apps.codecov_auth.models import AccountsUsers
from shared.django_apps.codecov_auth.tests.factories import (
    AccountFactory,
    OwnerFactory,
    UserFactory,
)

from tasks.activate_account_user import ActivateAccountUserTask


@pytest.fixture
def mock_db_session(mocker: MockFixture) -> Any:
    return mocker.Mock()


@pytest.mark.django_db
def test_activate_account_user_skip_no_account(
    caplog: LogCaptureFixture, mock_db_session: Any
) -> None:
    user = OwnerFactory()
    org = OwnerFactory()
    org.account = None
    ActivateAccountUserTask().run_impl(
        mock_db_session, user_ownerid=user.ownerid, org_ownerid=org.ownerid
    )
    assert len(caplog.records) == 2
    assert (
        caplog.records[1].message
        == "Organization does not have an account. Skipping account user activation."
    )


@pytest.mark.parametrize(
    "plan_seat_count,free_seat_count,is_user_student,expected_user_count",
    [
        pytest.param(0, 0, False, 0, id="cannot_activate_no_seats_available"),
        pytest.param(1, 0, False, 1, id="activate_with_seats_available"),
        pytest.param(0, 1, False, 1, id="activate_with_free_seats_available"),
        pytest.param(2, 0, True, 1, id="activate_github_student"),
        pytest.param(2, 1, True, 1, id="activate_github_student"),
    ],
)
@pytest.mark.django_db
def test_activate_account_user(
    plan_seat_count: int,
    free_seat_count: int,
    is_user_student: bool,
    expected_user_count: int,
    mock_db_session: Any,
) -> None:
    user = OwnerFactory()
    user.student = is_user_student
    user.user = UserFactory()
    org = OwnerFactory()
    account = AccountFactory(
        plan_seat_count=plan_seat_count, free_seat_count=free_seat_count
    )
    org.account = account
    org.save()
    assert AccountsUsers.objects.count() == 0

    ActivateAccountUserTask().run_impl(
        mock_db_session, user_ownerid=user.ownerid, org_ownerid=org.ownerid
    )
    assert AccountsUsers.objects.count() == expected_user_count
    if expected_user_count > 0:
        assert AccountsUsers.objects.first().account == account
        assert AccountsUsers.objects.first().user.owners.first() == user


@pytest.mark.django_db
def test_activate_account_user_already_exists(mock_db_session: Any) -> None:
    user = OwnerFactory()
    user.user = UserFactory()
    org = OwnerFactory()
    account = AccountFactory()
    org.account = account
    org.save()

    account.users.add(user.user)
    account.save()
    user.save()

    assert AccountsUsers.objects.filter(account=account, user=user.user).count() == 1

    ActivateAccountUserTask().run_impl(
        mock_db_session, user_ownerid=user.ownerid, org_ownerid=org.ownerid
    )

    # Nothing happens... user already exists.
    assert AccountsUsers.objects.filter(account=account, user=user.user).count() == 1
