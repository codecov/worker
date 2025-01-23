from shared.django_apps.codecov_auth.models import BillingRate
from shared.django_apps.codecov_auth.tests.factories import PlanFactory, TierFactory
from shared.plan.constants import PlanName, PlanPrice, TierName


def mock_all_plans_and_tiers():
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
        name=PlanName.BASIC_PLAN_NAME.value,
        tier=basic_tier,
        marketing_name="Developer",
        benefits=[
            "Up to 1 user",
            "Unlimited public repositories",
            "Unlimited private repositories",
        ],
        monthly_uploads_limit=250,
    )
    PlanFactory(
        name=PlanName.FREE_PLAN_NAME.value,
        tier=basic_tier,
        marketing_name="Developer",
        benefits=[
            "Up to 1 user",
            "Unlimited public repositories",
            "Unlimited private repositories",
        ],
    )

    pro_tier = TierFactory(tier_name=TierName.PRO.value)
    PlanFactory(
        name=PlanName.CODECOV_PRO_MONTHLY.value,
        tier=pro_tier,
        marketing_name="Pro",
        benefits=[
            "Configurable # of users",
            "Unlimited public repositories",
            "Unlimited private repositories",
            "Priority Support",
        ],
        billing_rate=BillingRate.MONTHLY.value,
        base_unit_price=PlanPrice.MONTHLY.value,
        paid_plan=True,
    )
    PlanFactory(
        name=PlanName.CODECOV_PRO_YEARLY.value,
        tier=pro_tier,
        marketing_name="Pro",
        benefits=[
            "Configurable # of users",
            "Unlimited public repositories",
            "Unlimited private repositories",
            "Priority Support",
        ],
        billing_rate=BillingRate.ANNUALLY.value,
        base_unit_price=PlanPrice.YEARLY.value,
        paid_plan=True,
    )
    PlanFactory(
        name=PlanName.CODECOV_PRO_MONTHLY_LEGACY.value,
        tier=pro_tier,
        marketing_name="Pro",
        benefits=[
            "Configurable # of users",
            "Unlimited public repositories",
            "Unlimited private repositories",
            "Priority Support",
        ],
    )
    PlanFactory(
        name=PlanName.CODECOV_PRO_YEARLY_LEGACY.value,
        tier=pro_tier,
        marketing_name="Pro",
        benefits=[
            "Configurable # of users",
            "Unlimited public repositories",
            "Unlimited private repositories",
            "Priority Support",
        ],
    )

    team_tier = TierFactory(tier_name=TierName.TEAM.value)
    PlanFactory(
        name=PlanName.TEAM_MONTHLY.value,
        tier=team_tier,
        marketing_name="Team",
        benefits=[
            "Up to 10 users",
            "Unlimited repositories",
            "2500 private repo uploads",
            "Patch coverage analysis",
        ],
        billing_rate=BillingRate.MONTHLY.value,
        base_unit_price=PlanPrice.TEAM_MONTHLY.value,
        monthly_uploads_limit=2500,
        paid_plan=True,
    )
    PlanFactory(
        name=PlanName.TEAM_YEARLY.value,
        tier=team_tier,
        marketing_name="Team",
        benefits=[
            "Up to 10 users",
            "Unlimited repositories",
            "2500 private repo uploads",
            "Patch coverage analysis",
        ],
        billing_rate=BillingRate.ANNUALLY.value,
        base_unit_price=PlanPrice.TEAM_YEARLY.value,
        monthly_uploads_limit=2500,
        paid_plan=True,
    )

    sentry_tier = TierFactory(tier_name=TierName.SENTRY.value)
    PlanFactory(
        name=PlanName.SENTRY_MONTHLY.value,
        tier=sentry_tier,
        marketing_name="Sentry Pro",
        billing_rate=BillingRate.MONTHLY.value,
        base_unit_price=PlanPrice.MONTHLY.value,
        paid_plan=True,
        benefits=[
            "Includes 5 seats",
            "$12 per additional seat",
            "Unlimited public repositories",
            "Unlimited private repositories",
            "Priority Support",
        ],
    )
    PlanFactory(
        name=PlanName.SENTRY_YEARLY.value,
        tier=sentry_tier,
        marketing_name="Sentry Pro",
        billing_rate=BillingRate.ANNUALLY.value,
        base_unit_price=PlanPrice.YEARLY.value,
        paid_plan=True,
        benefits=[
            "Includes 5 seats",
            "$10 per additional seat",
            "Unlimited public repositories",
            "Unlimited private repositories",
            "Priority Support",
        ],
    )

    enterprise_tier = TierFactory(tier_name=TierName.ENTERPRISE.value)
    PlanFactory(
        name=PlanName.ENTERPRISE_CLOUD_MONTHLY.value,
        tier=enterprise_tier,
        marketing_name="Enterprise",
        billing_rate=BillingRate.MONTHLY.value,
        base_unit_price=PlanPrice.MONTHLY.value,
        paid_plan=True,
    )
    PlanFactory(
        name=PlanName.ENTERPRISE_CLOUD_YEARLY.value,
        tier=enterprise_tier,
        marketing_name="Enterprise",
        billing_rate=BillingRate.ANNUALLY.value,
        base_unit_price=PlanPrice.YEARLY.value,
        paid_plan=True,
    )
