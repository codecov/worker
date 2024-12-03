from database.enums import TrialStatus
from database.tests.factories.core import OwnerFactory
from shared.billing import BillingPlan
from tasks.trial_expiration import TrialExpirationTask


class TestTrialExpiration(object):
    def test_trial_expiration_task_with_pretrial_users_count(self, dbsession, mocker):
        owner = OwnerFactory.create(pretrial_users_count=5)
        dbsession.add(owner)
        dbsession.flush()

        task = TrialExpirationTask()
        assert task.run_impl(dbsession, owner.ownerid) == {"successful": True}

        assert owner.plan == BillingPlan.users_basic.value
        assert owner.plan_activated_users is None
        assert owner.plan_user_count == 5
        assert owner.stripe_subscription_id is None
        assert owner.trial_status == TrialStatus.EXPIRED.value

    def test_trial_expiration_task_without_pretrial_users_count(
        self, dbsession, mocker
    ):
        owner = OwnerFactory.create()
        dbsession.add(owner)
        dbsession.flush()

        task = TrialExpirationTask()
        assert task.run_impl(dbsession, owner.ownerid) == {"successful": True}

        assert owner.plan == BillingPlan.users_basic.value
        assert owner.plan_activated_users is None
        assert owner.plan_user_count == 1
        assert owner.stripe_subscription_id is None
        assert owner.trial_status == TrialStatus.EXPIRED.value

    def test_trial_expiration_task_with_trial_fired_by(self, dbsession, mocker):
        owner = OwnerFactory.create(trial_fired_by=9)
        dbsession.add(owner)
        dbsession.flush()

        task = TrialExpirationTask()
        assert task.run_impl(dbsession, owner.ownerid) == {"successful": True}

        assert owner.plan == BillingPlan.users_basic.value
        assert owner.plan_activated_users == [9]
        assert owner.stripe_subscription_id is None
        assert owner.trial_status == TrialStatus.EXPIRED.value
