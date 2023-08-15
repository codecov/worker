from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from celery_config import trial_expiration_task_name
from database.enums import TrialStatus
from database.tests.factories.core import OwnerFactory
from services.billing import BillingPlan
from tasks.trial_expiration_cron import TrialExpirationCronTask


class TestTrialExpirationCheck(object):
    @pytest.mark.asyncio
    @patch("tasks.trial_expiration_cron.yield_amount", 1)
    async def test_enqueue_trial_expiration_task(self, dbsession, mocker):
        mocked_now = datetime(2023, 7, 3, 6, 8, 12)
        mocker.patch(
            "tasks.trial_expiration_cron.get_utc_now",
            return_value=mocked_now,
        )
        yesterday = mocked_now + timedelta(days=-1)
        tomorrow = mocked_now + timedelta(days=10)

        ongoing_owner_that_should_expire = OwnerFactory.create(
            username="one",
            trial_status=TrialStatus.ONGOING.value,
            trial_end_date=yesterday,
            plan=BillingPlan.users_trial.value,
        )
        second_ongoing_owner_that_should_expire = OwnerFactory.create(
            username="two",
            trial_status=TrialStatus.ONGOING.value,
            trial_end_date=yesterday,
            plan=BillingPlan.users_trial.value,
        )
        # These are to represent other types of owners we could face that we should not see
        ongoing_owner_that_should_not_expire = OwnerFactory.create(
            username="three",
            trial_status=TrialStatus.ONGOING.value,
            trial_end_date=tomorrow,
            plan=BillingPlan.users_trial.value,
        )
        expired_basic_owner = OwnerFactory.create(
            trial_status=TrialStatus.EXPIRED.value,
            trial_end_date=yesterday,
            plan=BillingPlan.users_basic.value,
        )
        expired_paid_owner = OwnerFactory.create(
            trial_status=TrialStatus.EXPIRED.value,
            trial_end_date=yesterday,
            plan=BillingPlan.pr_monthly.value,
        )
        cannot_trial_paid_owner = OwnerFactory.create(
            trial_status=TrialStatus.CANNOT_TRIAL.value,
            trial_end_date=yesterday,
            plan=BillingPlan.pr_monthly.value,
        )
        not_started_basic_owner = OwnerFactory.create(
            trial_status=TrialStatus.NOT_STARTED.value,
            trial_end_date=None,
            plan=BillingPlan.users_basic.value,
        )
        dbsession.add(ongoing_owner_that_should_expire)
        dbsession.add(second_ongoing_owner_that_should_expire)
        dbsession.add(ongoing_owner_that_should_not_expire)
        dbsession.add(expired_basic_owner)
        dbsession.add(expired_paid_owner)
        dbsession.add(cannot_trial_paid_owner)
        dbsession.add(not_started_basic_owner)
        dbsession.flush()

        mocked_app = mocker.patch.object(
            TrialExpirationCronTask,
            "app",
            tasks={
                trial_expiration_task_name: mocker.MagicMock(),
            },
        )
        task = TrialExpirationCronTask()

        assert await task.run_cron_task(dbsession) == {"successful": True}
        mocked_app.tasks[trial_expiration_task_name].apply_async.assert_any_call(
            kwargs={"ownerid": second_ongoing_owner_that_should_expire.ownerid}
        )
        mocked_app.tasks[trial_expiration_task_name].apply_async.assert_any_call(
            kwargs={"ownerid": ongoing_owner_that_should_expire.ownerid}
        )
        # TODO: couldn't find a way to assert I didn't call the other owners

    @pytest.mark.asyncio
    async def test_get_min_seconds_interval_between_executions(self, dbsession):
        assert isinstance(
            TrialExpirationCronTask.get_min_seconds_interval_between_executions(), int
        )
        # The specifics don't matter, but the number needs to be somewhat big
        assert (
            TrialExpirationCronTask.get_min_seconds_interval_between_executions() > 600
        )
