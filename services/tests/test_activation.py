from datetime import datetime

from database.tests.factories import OwnerFactory
from services.activation import activate_user, get_installation_plan_activated_users


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
        self, request, dbsession, mocker, mock_configuration, with_sql_functions
    ):
        mocker.patch("services.license.is_enterprise", return_value=True)
        mocker.patch("services.license._get_now", return_value=datetime(2020, 4, 2))

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

    def test_activate_user_success_user_org_overlap(
        self, request, dbsession, mock_configuration, mocker, with_sql_functions
    ):
        mocker.patch("services.license.is_enterprise", return_value=True)
        mocker.patch("services.license._get_now", return_value=datetime(2020, 4, 2))

        # Create two orgs to ensure our seat availability checking works across
        # multiple organizations.
        org = OwnerFactory.create(
            service="github",
            oauth_token=None,
            plan_activated_users=list(range(1, 6)),
            plan_auto_activate=True,
        )
        dbsession.add(org)
        dbsession.flush()

        org_second = OwnerFactory.create(
            service="github",
            oauth_token=None,
            plan_activated_users=list(range(2, 8)),
            plan_auto_activate=True,
        )
        dbsession.add(org_second)
        dbsession.flush()

        assert get_installation_plan_activated_users(dbsession)[0][0] == 7

        # {'company': 'Test Company', 'expires': '2021-01-01 00:00:00', 'url': 'https://codecov.mysite.com', 'trial': False, 'users': 10, 'repos': None, 'pr_billing': True}
        encrypted_license = "wxWEJyYgIcFpi6nBSyKQZQeaQ9Eqpo3SXyUomAqQOzOFjdYB3A8fFM1rm+kOt2ehy9w95AzrQqrqfxi9HJIb2zLOMOB9tSy52OykVCzFtKPBNsXU/y5pQKOfV7iI3w9CHFh3tDwSwgjg8UsMXwQPOhrpvl2GdHpwEhFdaM2O3vY7iElFgZfk5D9E7qEnp+WysQwHKxDeKLI7jWCnBCBJLDjBJRSz0H7AfU55RQDqtTrnR+rsLDHOzJ80/VxwVYhb"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.mysite.com"

        user = OwnerFactory.create_from_test_request(request)
        dbsession.add(org_second)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org_second.ownerid, user.ownerid)
        assert was_activated is True
        dbsession.commit()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is True
        dbsession.commit()

        assert get_installation_plan_activated_users(dbsession)[0][0] == 8

    def test_activate_user_failure_for_enterprise_pr_billing_no_seats(
        self, request, dbsession, mock_configuration, mocker, with_sql_functions
    ):
        mocker.patch("services.license.is_enterprise", return_value=True)
        mocker.patch("services.license._get_now", return_value=datetime(2020, 4, 2))

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

    def test_activate_user_enterprise_pr_billing_invalid_license(
        self, request, dbsession, mocker, mock_configuration, with_sql_functions
    ):
        mocker.patch("services.license.is_enterprise", return_value=True)

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
        assert was_activated is False

    def test_pr_billing_enterprise_no_seats_for_auto_actiavation(
        self, request, dbsession, mocker, mock_configuration, with_sql_functions
    ):
        mocker.patch("services.license.is_enterprise", return_value=True)
        mocker.patch("services.license._get_now", return_value=datetime(2020, 4, 2))

        user = OwnerFactory.create_from_test_request(request)
        dbsession.add(user)
        dbsession.flush()

        org = OwnerFactory.create(
            service="github",
            oauth_token=None,
            plan_activated_users=[user.ownerid],
            plan_auto_activate=True,
        )
        dbsession.add(org)
        dbsession.flush()

        encrypted_license = "AtFDCJPhzM0SEF6MdCay6SwaDEZjkIlxH64UAo+Qm2auVe7SsfwxvjgXviKYBK2t+mQSbQQIc9hluF4oI6r+8ZpVCYvOnHv/Qp7Ism747cGKHHGpePm/E3MDaFTGyRdTaGach9K0/3UdoGJh9Gcf1FhEiutHV2qmhWLKQFLdD9QJu31vFGChS63NH864XV3Hp62GEmhuV+/tyVNTVmh7UXShaNVEC8CU+714TUVYO0SWuysPDr6wv6mBskZE5Evb"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.mysite.com"

        # Make a new user, this would be the 11th activated user
        second_user = OwnerFactory.create_from_test_request(request)
        dbsession.add(second_user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, second_user.ownerid)
        assert was_activated is False
