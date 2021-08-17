import logging
from enum import Enum

from shared.license import get_current_license

from services.license import requires_license

log = logging.getLogger(__name__)


class BillingPlan(Enum):
    users_monthly = "users-inappm"
    users_yearly = "users-inappy"
    users_free = "users-free"
    pr_monthly = "users-pr-inappm"
    pr_yearly = "users-pr-inappy"


def is_pr_billing_plan(plan: str) -> bool:
    if not requires_license():
        return plan in [
            BillingPlan.pr_monthly.value,
            BillingPlan.pr_yearly.value,
            BillingPlan.users_free.value,
        ]
    else:
        license = get_current_license()
        if license.is_pr_billing:
            return True
        return False
