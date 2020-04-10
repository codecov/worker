import logging
from enum import Enum

log = logging.getLogger(__name__)


class BillingPlan(Enum):
    users_monthly = "users-inappm"
    users_yearly = "users-inappy"
    users_free = "users-free"
    pr_monthly = "users-inappm-pr"
    pr_yearly = "users-inappy-pr"


def is_pr_billing_plan(plan):
    return plan in [BillingPlan.pr_monthly.value, BillingPlan.pr_yearly.value]
