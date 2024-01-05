import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func

from conftest import dbsession
from database.enums import Decoration, ReportType, TrialStatus
from database.models import Commit, Owner, Repository
from database.models.reports import CommitReport, Upload
from services.billing import BillingPlan, is_pr_billing_plan
from services.license import requires_license
from services.repository import EnrichedPull

log = logging.getLogger(__name__)

# For more context on PR decorations, see here:
# https://codecovio.atlassian.net/wiki/spaces/ENG/pages/34603058/PR+based+Billing+Refactor


BOT_USER_EMAILS = [
    "dependabot[bot]@users.noreply.github.com",
    "29139614+renovate[bot]@users.noreply.github.com",
]
BOT_USER_IDS = ["29139614"]  # renovate[bot] github
USER_BASIC_LIMIT_UPLOAD = 250

PLANS_WITH_UPLOAD_LIMIT = {
    "users-basic": 250,
    "users-teamm": 2500,
    "users-teamy": 2500,
}

WHITELISTED_ORGS = ["drazisil-org"]


@dataclass
class DecorationDetails(object):
    decoration_type: Decoration
    reason: str
    should_attempt_author_auto_activation: bool = False
    activation_org_ownerid: int = None
    activation_author_ownerid: int = None


def _is_bot_account(author: Owner) -> bool:
    return author.email in BOT_USER_EMAILS or author.service_id in BOT_USER_IDS


def determine_uploads_used(db_session, org: Owner) -> int:
    query = (
        db_session.query(Upload)
        .join(CommitReport)
        .join(Commit)
        .join(Repository)
        .filter(
            Upload.upload_type == "uploaded",
            Repository.ownerid == org.ownerid,
            Repository.private == True,
            Upload.created_at >= (datetime.now() - timedelta(days=30)),
            Commit.timestamp >= (datetime.now() - timedelta(days=60)),
            (CommitReport.report_type == None)
            | (CommitReport.report_type == ReportType.COVERAGE.value),
        )
    )

    if (
        org.trial_status == TrialStatus.EXPIRED.value
        and org.trial_start_date
        and org.trial_end_date
    ):
        query = query.filter(
            (Upload.created_at >= org.trial_end_date)
            | (Upload.created_at <= org.trial_start_date)
        )

    # Upload limit of the user's plan, default to USER_BASIC_LIMIT_UPLOAD if not found
    plan_allowed_limit = PLANS_WITH_UPLOAD_LIMIT.get(org.plan, USER_BASIC_LIMIT_UPLOAD)

    return query.limit(plan_allowed_limit).count()


def determine_decoration_details(
    enriched_pull: EnrichedPull, empty_upload=None
) -> dict:
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
            # public repo or repo we arent certain is private should be standard
            return DecorationDetails(
                decoration_type=Decoration.standard, reason="Public repo"
            )

        org = db_pull.repository.owner

        db_session = db_pull.get_db_session()

        if org.service == "gitlab" and org.parent_service_id:
            # need to get root group so we can check plan info
            (gl_root_group,) = db_session.query(
                func.public.get_gitlab_root_group(org.ownerid)
            ).first()

            org = (
                db_session.query(Owner)
                .filter(Owner.ownerid == gl_root_group.get("ownerid"))
                .first()
            )

        if not is_pr_billing_plan(org.plan):
            if org.username not in WHITELISTED_ORGS:
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

        # TODO declare this to be shared between codecov-api and worker
        uploads_used = determine_uploads_used(db_session=db_session, org=org)

        if (
            org.plan in PLANS_WITH_UPLOAD_LIMIT
            and uploads_used >= PLANS_WITH_UPLOAD_LIMIT[org.plan]
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
