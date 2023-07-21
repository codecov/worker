import pytest

from database.enums import TrialStatus
from database.tests.factories.core import OwnerFactory
from services.billing import BillingPlan
from tasks.trial_expiration import TrialExpirationTask


class TestTrialExpiration(object):
    @pytest.mark.asyncio
    async def test_trial_expiration_task(self, dbsession, mocker):
        owner = OwnerFactory.create()
        dbsession.add(owner)
        dbsession.flush()

        task = TrialExpirationTask()
        assert await task.run_async(dbsession, owner.ownerid) == {"successful": True}

        assert owner.plan == BillingPlan.users_basic.value
        assert owner.plan_activated_users == None
        assert owner.plan_user_count == 1
        assert owner.stripe_subscription_id == None
        assert owner.trial_status == TrialStatus.EXPIRED.value
