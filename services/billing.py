import logging
from enum import Enum

from shared.license import get_current_license

from services.license import requires_license

log = logging.getLogger(__name__)


class BillingPlan(Enum):
    users_monthly = "users-inappm"
    users_yearly = "users-inappy"
    users_free = "users-free"
    users_basic = "users-basic"
    users_trial = "users-trial"
    pr_monthly = "users-pr-inappm"
    pr_yearly = "users-pr-inappy"
    enterprise_cloud_yearly = "users-enterprisey"
    enterprise_cloud_monthly = "users-enterprisem"


def is_pr_billing_plan(plan: str) -> bool:
    if not requires_license():
        return plan in [
            BillingPlan.pr_monthly.value,
            BillingPlan.pr_yearly.value,
            BillingPlan.users_free.value,
            BillingPlan.users_basic.value,
            BillingPlan.users_trial.value,
            BillingPlan.enterprise_cloud_monthly.value,
            BillingPlan.enterprise_cloud_yearly.value,
        ]
    else:
        license = get_current_license()
        if license.is_pr_billing:
            return True
        return False
