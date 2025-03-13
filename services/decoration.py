import logging
from dataclasses import dataclass

from shared.config import get_config
from shared.plan.service import PlanService
from shared.upload.utils import query_monthly_coverage_measurements

from database.enums import Decoration
from database.models import Owner
from services.license import requires_license
from services.repository import EnrichedPull

log = logging.getLogger(__name__)

# For more context on PR decorations, see here:
# https://codecovio.atlassian.net/wiki/spaces/ENG/pages/34603058/PR+based+Billing+Refactor


BOT_USER_EMAILS = [
    "dependabot[bot]@users.noreply.github.com",
    "29139614+renovate[bot]@users.noreply.github.com",
    "157164994+sentry-autofix[bot]@users.noreply.github.com",
]
BOT_USER_IDS = ["29139614", "157164994"]  # renovate[bot] github, sentry-autofix[bot]
USER_BASIC_LIMIT_UPLOAD = 250


@dataclass
class DecorationDetails(object):
    decoration_type: Decoration
    reason: str
    should_attempt_author_auto_activation: bool = False
    activation_org_ownerid: int | None = None
    activation_author_ownerid: int | None = None


def _is_bot_account(author: Owner) -> bool:
    return author.email in BOT_USER_EMAILS or author.service_id in BOT_USER_IDS


def determine_uploads_used(plan_service: PlanService) -> int:
    # This query takes an absurdly long time to run and in some environments we
    # would like to disable it
    if not get_config("setup", "upload_throttling_enabled", default=True):
        return 0

    return query_monthly_coverage_measurements(plan_service=plan_service)


def determine_decoration_details(
    enriched_pull: EnrichedPull, empty_upload=None
) -> DecorationDetails:
    """
    Determine the decoration details from pull information. We also check if the pull author needs to be activated

    Returns:
        DecorationDetails: the decoration type and reason along with whether auto-activation of the author should be attempted
    """
    if enriched_pull:
        db_pull = enriched_pull.database_pull
        provider_pull = enriched_pull.provider_pull

        if not provider_pull:
            return DecorationDetails(
                decoration_type=Decoration.standard,
                reason="Can't determine PR author - no pull info from provider",
            )
        if empty_upload == "pass":
            return DecorationDetails(
                decoration_type=Decoration.passing_empty_upload,
                reason="Non testable files got changed.",
            )

        if empty_upload == "fail":
            return DecorationDetails(
                decoration_type=Decoration.failing_empty_upload,
                reason="Testable files got changed.",
            )

        if empty_upload == "processing":
            return DecorationDetails(
                decoration_type=Decoration.processing_upload,
                reason="Upload is still processing.",
            )

        if db_pull.repository.private is False:
            # public repo or repo we aren't certain is private should be standard
            return DecorationDetails(
                decoration_type=Decoration.standard, reason="Public repo"
            )

        org = db_pull.repository.owner

        db_session = db_pull.get_db_session()

        # do not access plan directly - only through PlanService
        org_plan = PlanService(current_org=org)
        # use the org that has the plan - for GL this is the root_org rather than the repository.owner org
        org = org_plan.current_org

        if not org_plan.is_pr_billing_plan:
            return DecorationDetails(
                decoration_type=Decoration.standard, reason="Org not on PR plan"
            )

        pr_author = (
            db_session.query(Owner)
            .filter(
                Owner.service == org.service,
                Owner.service_id == provider_pull["author"]["id"],
            )
            .first()
        )

        if not pr_author:
            log.info(
                "PR author not found in database",
                extra=dict(
                    author_service=org.service,
                    author_service_id=provider_pull["author"]["id"],
                    author_username=provider_pull["author"]["username"],
                ),
            )
            return DecorationDetails(
                decoration_type=Decoration.upgrade,
                reason="PR author not found in database",
            )

        monthly_limit = org_plan.monthly_uploads_limit
        if monthly_limit is not None:
            uploads_used = determine_uploads_used(plan_service=org_plan)

            if (
                uploads_used >= org_plan.monthly_uploads_limit
                and not requires_license()
            ):
                return DecorationDetails(
                    decoration_type=Decoration.upload_limit,
                    reason="Org has exceeded the upload limit",
                )

        if (
            org.plan_activated_users is not None
            and pr_author.ownerid in org.plan_activated_users
        ):
            return DecorationDetails(
                decoration_type=Decoration.standard,
                reason="User is currently activated",
            )

        if _is_bot_account(pr_author):
            return DecorationDetails(
                decoration_type=Decoration.standard,
                reason="Bot user detected (does not need to be activated)",
            )

        if not org.plan_auto_activate:
            return DecorationDetails(
                decoration_type=Decoration.upgrade,
                reason="User must be manually activated",
            )
        else:
            return DecorationDetails(
                decoration_type=Decoration.upgrade,
                reason="User must be activated",
                should_attempt_author_auto_activation=True,
                activation_org_ownerid=org.ownerid,
                activation_author_ownerid=pr_author.ownerid,
            )
    return DecorationDetails(decoration_type=Decoration.standard, reason="No pull")
