import logging
from enum import Enum

log = logging.getLogger(__name__)


class BillingPlan(Enum):
    users_monthly = "users-inappm"
    users_yearly = "users-inappy"
    users_free = "users-free"
    pr_monthly = "users-pr-inappm"
    pr_yearly = "users-pr-inappy"
    pr_github_marketplace = "users"


def is_pr_billing_plan(plan: str) -> bool:
    return plan in [
        BillingPlan.pr_monthly.value,
        BillingPlan.pr_yearly.value,
        BillingPlan.users_free.value,
        BillingPlan.pr_github_marketplace.value
    ]
