from enum import Enum

from django.conf import settings

from shared.license import get_current_license


class BillingPlan(Enum):
    users_ghm = "users"
    users_monthly = "users-inappm"
    users_yearly = "users-inappy"
    users_free = "users-free"
    users_basic = "users-basic"
    users_trial = "users-trial"
    pr_monthly = "users-pr-inappm"
    pr_yearly = "users-pr-inappy"
    enterprise_cloud_yearly = "users-enterprisey"
    enterprise_cloud_monthly = "users-enterprisem"
    team_monthly = "users-teamm"
    team_yearly = "users-teamy"

    def __init__(self, db_name):
        self.db_name = db_name

    @classmethod
    def from_str(cls, plan_name: str):
        for plan in cls:
            if plan.db_name == plan_name:
                return plan


def is_enterprise_cloud_plan(plan: BillingPlan) -> bool:
    return plan in [
        BillingPlan.enterprise_cloud_monthly,
        BillingPlan.enterprise_cloud_yearly,
    ]


def is_pr_billing_plan(plan: str) -> bool:
    if not settings.IS_ENTERPRISE:
        return plan in [
            BillingPlan.pr_monthly.value,
            BillingPlan.pr_yearly.value,
            BillingPlan.users_free.value,
            BillingPlan.users_basic.value,
            BillingPlan.users_trial.value,
            BillingPlan.enterprise_cloud_monthly.value,
            BillingPlan.enterprise_cloud_yearly.value,
            BillingPlan.team_monthly.value,
            BillingPlan.team_yearly.value,
            BillingPlan.users_ghm.value,
        ]
    else:
        return get_current_license().is_pr_billing
