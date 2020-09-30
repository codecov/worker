import pytest

from database.tests.factories import OwnerFactory

from services.activation import activate_user


class TestActivationServiceTestCase(object):
    def test_activate_user_no_seats(self, dbsession, mocker, with_sql_functions):
        org = OwnerFactory.create(
            plan_user_count=0, plan_activated_users=[], plan_auto_activate=True
        )
        user = OwnerFactory.create()
        dbsession.add(org)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is False
        dbsession.commit()
        assert user.ownerid not in org.plan_activated_users

    def test_activate_user_success(self, dbsession, mocker, with_sql_functions):
        org = OwnerFactory.create(
            plan_user_count=1, plan_activated_users=[], plan_auto_activate=True
        )
        user = OwnerFactory.create()
        dbsession.add(org)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is True
        dbsession.commit()
        assert user.ownerid in org.plan_activated_users

    def test_activate_user_success_for_users_free(
        self, dbsession, mocker, with_sql_functions
    ):
        org = OwnerFactory.create(
            plan="users-free",
            plan_user_count=1,
            plan_activated_users=None,
            plan_auto_activate=True,
        )
        user = OwnerFactory.create()
        dbsession.add(org)
        dbsession.add(user)
        dbsession.flush()

        was_activated = activate_user(dbsession, org.ownerid, user.ownerid)
        assert was_activated is True
        dbsession.commit()
        assert user.ownerid in org.plan_activated_users
