from django.test import override_settings
from shared.billing import BillingPlan, is_pr_billing_plan

from database.tests.factories import OwnerFactory


class TestBillingServiceTestCase(object):
    def test_pr_author_plan_check(self, request, dbsession, with_sql_functions):
        owner = OwnerFactory.create(service="github", plan="users-pr-inappm")
        dbsession.add(owner)
        dbsession.flush()
        assert is_pr_billing_plan(owner.plan)

    @override_settings(IS_ENTERPRISE=True)
    def test_pr_author_enterprise_plan_check(
        self, request, dbsession, mock_configuration, with_sql_functions
    ):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()

        encrypted_license = "wxWEJyYgIcFpi6nBSyKQZQeaQ9Eqpo3SXyUomAqQOzOFjdYB3A8fFM1rm+kOt2ehy9w95AzrQqrqfxi9HJIb2zLOMOB9tSy52OykVCzFtKPBNsXU/y5pQKOfV7iI3w9CHFh3tDwSwgjg8UsMXwQPOhrpvl2GdHpwEhFdaM2O3vY7iElFgZfk5D9E7qEnp+WysQwHKxDeKLI7jWCnBCBJLDjBJRSz0H7AfU55RQDqtTrnR+rsLDHOzJ80/VxwVYhb"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codecov.mysite.com"
        )

        assert is_pr_billing_plan(owner.plan)

    def test_plan_not_pr_author(self, request, dbsession, with_sql_functions):
        owner = OwnerFactory.create(
            service="github", plan=BillingPlan.users_monthly.value
        )
        dbsession.add(owner)
        dbsession.flush()

        assert not is_pr_billing_plan(owner.plan)

    @override_settings(IS_ENTERPRISE=True)
    def test_pr_author_enterprise_plan_check_non_pr_plan(
        self, request, dbsession, mocker, mock_configuration, with_sql_functions
    ):
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()

        encrypted_license = "0dRbhbzp8TVFQp7P4e2ES9lSfyQlTo8J7LQ"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_dashboard_url"] = (
            "https://codeov.mysite.com"
        )

        assert not is_pr_billing_plan(owner.plan)
