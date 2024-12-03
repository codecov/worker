from django.test import override_settings

from database.tests.factories import OwnerFactory
from shared.billing import BillingPlan, is_pr_billing_plan


class TestBillingServiceTestCase(object):
    def test_pr_author_plan_check(
        self, request, dbsession, with_sql_functions
    ):
        owner = OwnerFactory.create(service="github", plan="users-pr-inappm")
        dbsession.add(owner)
        dbsession.flush()
        assert is_pr_billing_plan(owner.plan)

    @override_settings(IS_ENTERPRISE=True)
    def test_pr_author_enterprise_plan_check(
        self, request, dbsession, with_sql_functions
    ):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()

        assert is_pr_billing_plan(owner.plan)

    def test_plan_not_pr_author(
        self, request, dbsession, with_sql_functions
    ):
        owner = OwnerFactory.create(
            service="github", plan=BillingPlan.users_monthly.value
        )
        dbsession.add(owner)
        dbsession.flush()

        assert not is_pr_billing_plan(owner.plan)

    @override_settings(IS_ENTERPRISE=True)
    def test_pr_author_enterprise_plan_check_non_pr_plan(
        self, request, dbsession, with_sql_functions
    ):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()

        assert not is_pr_billing_plan(owner.plan)
