import pytest

from database.models.core import OrganizationLevelToken
from database.tests.factories.core import OrgLevelTokenFactory, OwnerFactory
from services.billing import BillingPlan
from tasks.plan_manager_task import DailyPlanManagerTask


class TestDailyPlanManagerTask(object):
    @pytest.mark.asyncio
    async def test_simple_case(self, dbsession):
        task = DailyPlanManagerTask()
        # Populate DB
        owner_in_enterprise_plan = OwnerFactory.create(
            service="github", plan=BillingPlan.enterprise_cloud_monthly.value
        )
        owner_not_in_enterprise_plan = OwnerFactory.create(
            service="github", plan=BillingPlan.users_free.value
        )

        valid_token = OrgLevelTokenFactory.create(owner=owner_in_enterprise_plan)
        invalid_token = OrgLevelTokenFactory.create(owner=owner_not_in_enterprise_plan)
        invalid_token_2 = OrgLevelTokenFactory.create(
            owner=owner_not_in_enterprise_plan
        )

        dbsession.add(valid_token)
        dbsession.add(invalid_token)
        dbsession.add(invalid_token_2)
        dbsession.flush()
        assert dbsession.query(OrganizationLevelToken).count() == 3

        result = await task.run_cron_task(dbsession)
        assert result.get("checked") == True
        assert result.get("deleted") == 2
        assert dbsession.query(OrganizationLevelToken).count() == 1
        assert (
            dbsession.query(OrganizationLevelToken).first().owner.ownerid
            == owner_in_enterprise_plan.ownerid
        )

    @pytest.mark.asyncio
    async def test_get_min_seconds_interval_between_executions(self, dbsession):
        assert isinstance(
            DailyPlanManagerTask.get_min_seconds_interval_between_executions(), int
        )
        # The specifics don't matter, but the number needs to be big
        assert (
            DailyPlanManagerTask.get_min_seconds_interval_between_executions() > 86000
        )
