import pytest

from database.tests.factories import OwnerFactory

from services.activation import activate_user

from services.license import (
    calculate_reason_for_not_being_valid,
    InvalidLicenseReason,
    has_valid_license,
    requires_license,
    is_properly_licensed,
)


class TestActivationServiceTestCase(object):
    def test_activate_user_no_seats(
        self, request, dbsession, mocker, with_sql_functions
    ):
        org = OwnerFactory.create(
            plan_user_count=0, plan_activated_users=[], plan_auto_activate=True
        )
        user = OwnerFactory.create_from_test_request(request)
        dbsession.add(org)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is False
        dbsession.commit()
        assert user.ownerid not in org.plan_activated_users

    def test_activate_user_success(
        self, request, dbsession, mocker, with_sql_functions
    ):
        org = OwnerFactory.create(
            plan_user_count=1, plan_activated_users=[], plan_auto_activate=True
        )
        user = OwnerFactory.create_from_test_request(request)
        dbsession.add(org)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is True
        dbsession.commit()
        assert user.ownerid in org.plan_activated_users

    def test_activate_user_success_for_users_free(
        self, request, dbsession, mocker, with_sql_functions
    ):
        org = OwnerFactory.create(
            plan="users-free",
            plan_user_count=1,
            plan_activated_users=None,
            plan_auto_activate=True,
        )
        user = OwnerFactory.create_from_test_request(request)
        dbsession.add(org)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is True
        dbsession.commit()
        assert user.ownerid in org.plan_activated_users

    def test_activate_user_success_for_enterprise_pr_billing(
        self, request, dbsession, mock_configuration, mocker, with_sql_functions
    ):

        mocker.patch("helpers.environment.is_enterprise", return_value=True)

        org = OwnerFactory.create(
            service="github",
            oauth_token=None,
            plan_activated_users=list(range(15, 20)),
            plan_auto_activate=True,
        )
        dbsession.add(org)
        dbsession.flush()

        encrypted_license = "wxWEJyYgIcFpi6nBSyKQZQeaQ9Eqpo3SXyUomAqQOzOFjdYB3A8fFM1rm+kOt2ehy9w95AzrQqrqfxi9HJIb2zLOMOB9tSy52OykVCzFtKPBNsXU/y5pQKOfV7iI3w9CHFh3tDwSwgjg8UsMXwQPOhrpvl2GdHpwEhFdaM2O3vY7iElFgZfk5D9E7qEnp+WysQwHKxDeKLI7jWCnBCBJLDjBJRSz0H7AfU55RQDqtTrnR+rsLDHOzJ80/VxwVYhb"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.mysite.com"

        user = OwnerFactory.create_from_test_request(request)
        dbsession.add(org)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is True
        dbsession.commit()
        assert user.ownerid in org.plan_activated_users

    def test_activate_user_failure_for_enterprise_pr_billing_no_seats(
        self, request, dbsession, mock_configuration, mocker, with_sql_functions
    ):

        mocker.patch("helpers.environment.is_enterprise", return_value=True)
        # Create two orgs to ensure our seat availability checking works across
        # multiple organizations.
        org = OwnerFactory.create(
            service="github",
            oauth_token=None,
            plan_activated_users=list(range(15, 20)),
            plan_auto_activate=True,
        )
        dbsession.add(org)
        dbsession.flush()

        org_second = OwnerFactory.create(
            service="github",
            oauth_token=None,
            plan_activated_users=list(range(21, 35)),
            plan_auto_activate=True,
        )
        dbsession.add(org_second)
        dbsession.flush()

        encrypted_license = "wxWEJyYgIcFpi6nBSyKQZQeaQ9Eqpo3SXyUomAqQOzOFjdYB3A8fFM1rm+kOt2ehy9w95AzrQqrqfxi9HJIb2zLOMOB9tSy52OykVCzFtKPBNsXU/y5pQKOfV7iI3w9CHFh3tDwSwgjg8UsMXwQPOhrpvl2GdHpwEhFdaM2O3vY7iElFgZfk5D9E7qEnp+WysQwHKxDeKLI7jWCnBCBJLDjBJRSz0H7AfU55RQDqtTrnR+rsLDHOzJ80/VxwVYhb"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.mysite.com"

        user = OwnerFactory.create_from_test_request(request)
        dbsession.add(org_second)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org_second.ownerid, user.ownerid)
        assert was_activated is False
        dbsession.commit()
        assert user.ownerid not in org.plan_activated_users
