import pytest
from shared.django_apps.codecov_auth.tests.factories import (
    OwnerFactory,
    PlanFactory,
    TierFactory,
)
from shared.plan.constants import DEFAULT_FREE_PLAN, PlanName, TierName

from database.enums import TrialStatus
from tasks.trial_expiration import TrialExpirationTask


@pytest.mark.django_db
class TestTrialExpiration(object):
    @pytest.fixture(autouse=True)
    def setup(self):
        trial_tier = TierFactory(tier_name=TierName.TRIAL.value)
        PlanFactory(
            tier=trial_tier,
            name=PlanName.TRIAL_PLAN_NAME.value,
            paid_plan=False,
            marketing_name="Developer",
            benefits=[
                "Configurable # of users",
                "Unlimited public repositories",
                "Unlimited private repositories",
                "Priority Support",
            ],
        )
        basic_tier = TierFactory(tier_name=TierName.BASIC.value)
        PlanFactory(
            name=DEFAULT_FREE_PLAN,
            tier=basic_tier,
            marketing_name="Developer",
            benefits=[
                "Up to 1 user",
                "Unlimited public repositories",
                "Unlimited private repositories",
            ],
            monthly_uploads_limit=250,
        )

    def test_trial_expiration_task_with_pretrial_users_count(self, db, mocker):
        """
        We used to save the plan_user_count as pretrial_users_count, and reinstate the original plan_user_count at the end of the trial.
        We no longer do this - when we cancel a trial, we set_default_plan_data(), which sets plan_user_count as 1
        """
        owner = OwnerFactory(
            pretrial_users_count=5,
            plan=PlanName.TRIAL_PLAN_NAME.value,
            trial_status=TrialStatus.ONGOING.value,
        )

        task = TrialExpirationTask()
        assert task.run_impl(db, owner.ownerid) == {"successful": True}

        owner.refresh_from_db()
        assert owner.plan == DEFAULT_FREE_PLAN
        assert owner.plan_activated_users is None
        assert owner.plan_user_count == 1
        assert owner.stripe_subscription_id is None
        assert owner.trial_status == TrialStatus.EXPIRED.value

    def test_trial_expiration_task_without_pretrial_users_count(self, db, mocker):
        owner = OwnerFactory(
            plan=PlanName.TRIAL_PLAN_NAME.value, trial_status=TrialStatus.ONGOING.value
        )

        task = TrialExpirationTask()
        assert task.run_impl(db, owner.ownerid) == {"successful": True}

        owner.refresh_from_db()
        assert owner.plan == DEFAULT_FREE_PLAN
        assert owner.plan_activated_users is None
        assert owner.plan_user_count == 1
        assert owner.stripe_subscription_id is None
        assert owner.trial_status == TrialStatus.EXPIRED.value

    def test_trial_expiration_task_with_trial_fired_by(self, db, mocker):
        """
        We used to set the trial_fired_by owner as the only plan_activated_users as part of expiring the trial.
        We no longer do this - when we cancel a trial, we set_default_plan_data(), which clears plan_activated_users.
        """
        owner = OwnerFactory(
            trial_fired_by=9,
            plan=PlanName.TRIAL_PLAN_NAME.value,
            trial_status=TrialStatus.ONGOING.value,
        )

        task = TrialExpirationTask()
        assert task.run_impl(db, owner.ownerid) == {"successful": True}

        owner.refresh_from_db()
        assert owner.plan == DEFAULT_FREE_PLAN
        assert owner.plan_activated_users is None
        assert owner.stripe_subscription_id is None
        assert owner.trial_status == TrialStatus.EXPIRED.value
