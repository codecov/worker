import logging
from datetime import datetime, timezone
from typing import Any, Mapping

import sentry_sdk
from asgiref.sync import async_to_sync
from shared.billing import BillingPlan
from shared.metrics import Counter, inc_counter
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitObjectNotFoundError,
    TorngitServerFailureError,
)

from database.enums import Notification
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison
from services.license import requires_license
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)
from services.notification.notifiers.comment.conditions import (
    ComparisonHasPull,
    HasEnoughBuilds,
    HasEnoughRequiredChanges,
    NotifyCondition,
    PullHeadMatchesComparisonHead,
    PullRequestInProvider,
)
from services.notification.notifiers.mixins.message import MessageMixin
from services.urls import append_tracking_params_to_urls, get_members_url, get_plan_url

log = logging.getLogger(__name__)

COMMENT_NOTIFIER_COUNTER = Counter(
    "notifiers_comment_pull_closed_notifying_anyways",
    "Number of comment notifier runs when pull is closed",
    ["repo_using_integration"],
)


class CommentNotifier(MessageMixin, AbstractBaseNotifier):
    notify_conditions: list[NotifyCondition] = [
        ComparisonHasPull,
        PullRequestInProvider,
        PullHeadMatchesComparisonHead,
        HasEnoughBuilds,
        HasEnoughRequiredChanges,
    ]

    def store_results(self, comparison: ComparisonProxy, result: NotificationResult):
        pull = comparison.pull
        if not result.notification_attempted or not result.notification_successful:
            return
        data_received = result.data_received
        if data_received:
            if data_received.get("id"):
                pull.commentid = data_received.get("id")
            elif data_received.get("deleted_comment"):
                pull.commentid = None

    @property
    def name(self) -> str:
        return "comment"

    @property
    def notification_type(self) -> Notification:
        return Notification.comment

    def get_diff(self, comparison: Comparison):
        return comparison.get_diff()

    @sentry_sdk.trace
    def notify(self, comparison: ComparisonProxy) -> NotificationResult:
        # TODO: remove this when we don't need it anymore
        # this line is measuring how often we try to comment on a PR that is closed
        if comparison.pull is not None and comparison.pull.state != "open":
            inc_counter(
                COMMENT_NOTIFIER_COUNTER,
                labels=dict(
                    repo_using_integration="true"
                    if self.repository_service.data["repo"]["using_integration"]
                    else "false",
                ),
            )

        for condition in self.notify_conditions:
            condition_result = condition.check_condition(
                notifier=self, comparison=comparison
            )
            if condition_result == False:
                side_effect_result = condition.on_failure_side_effect(self, comparison)
                default_result = NotificationResult(
                    notification_attempted=False,
                    explanation=condition.failure_explanation,
                    data_sent=None,
                    data_received=None,
                )
                return default_result.merge(side_effect_result)
        pull = comparison.pull
        try:
            message = self.build_message(comparison)
        except TorngitClientError:
            log.warning(
                "Unable to fetch enough information to build message for comment",
                extra=dict(
                    commit=comparison.head.commit.commitid,
                    pullid=comparison.pull.pullid,
                ),
                exc_info=True,
            )
            return NotificationResult(
                notification_attempted=False,
                explanation="unable_build_message",
                data_sent=None,
                data_received=None,
            )
        data = {"message": message, "commentid": pull.commentid, "pullid": pull.pullid}
        try:
            return self.send_actual_notification(data)
        except TorngitServerFailureError:
            log.warning(
                "Unable to send comments because the provider server was not reachable or errored",
                extra=dict(git_service=self.repository.service),
                exc_info=True,
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="provider_issue",
                data_sent=data,
                data_received=None,
            )

    def send_actual_notification(self, data: Mapping[str, Any]):
        message = "\n".join(data["message"])

        # Append tracking parameters to any codecov urls in the message
        message = append_tracking_params_to_urls(
            message,
            service=self.repository.service,
            notification_type="comment",
            org_name=self.repository.owner.name,
        )

        behavior = self.notifier_yaml_settings.get("behavior", "default")
        if behavior == "default":
            res = self.send_comment_default_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "once":
            res = self.send_comment_once_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "new":
            res = self.send_comment_new_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "spammy":
            res = self.send_comment_spammy_behavior(
                data["pullid"], data["commentid"], message
            )
        return NotificationResult(
            notification_attempted=res["notification_attempted"],
            notification_successful=res["notification_successful"],
            explanation=res["explanation"],
            data_sent=data,
            data_received=res["data_received"],
        )

    def send_comment_default_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                res = async_to_sync(self.repository_service.edit_comment)(
                    pullid, commentid, message
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": True,
                    "explanation": None,
                    "data_received": {"id": res["id"]},
                }
            except TorngitObjectNotFoundError:
                log.warning("Comment was not found to be edited")
            except TorngitClientError:
                log.warning(
                    "Comment could not be edited due to client permissions",
                    exc_info=True,
                    extra=dict(pullid=pullid, commentid=commentid),
                )
        try:
            res = async_to_sync(self.repository_service.post_comment)(pullid, message)
            return {
                "notification_attempted": True,
                "notification_successful": True,
                "explanation": None,
                "data_received": {"id": res["id"]},
            }
        except TorngitClientError:
            log.warning(
                "Comment could not be posted due to client permissions",
                exc_info=True,
                extra=dict(pullid=pullid, commentid=commentid),
            )
            return {
                "notification_attempted": True,
                "notification_successful": False,
                "explanation": "comment_posting_permissions",
                "data_received": None,
            }

    def send_comment_once_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                res = async_to_sync(self.repository_service.edit_comment)(
                    pullid, commentid, message
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": True,
                    "explanation": None,
                    "data_received": {"id": res["id"]},
                }
            except TorngitObjectNotFoundError:
                log.warning("Comment was not found to be edited")
                return {
                    "notification_attempted": False,
                    "notification_successful": None,
                    "explanation": "comment_deleted",
                    "data_received": None,
                }
            except TorngitClientError:
                log.warning(
                    "Comment could not be edited due to client permissions",
                    exc_info=True,
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": False,
                    "explanation": "no_permissions",
                    "data_received": None,
                }
        res = async_to_sync(self.repository_service.post_comment)(pullid, message)
        return {
            "notification_attempted": True,
            "notification_successful": True,
            "explanation": None,
            "data_received": {"id": res["id"]},
        }

    def send_comment_new_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                async_to_sync(self.repository_service.delete_comment)(pullid, commentid)
            except TorngitObjectNotFoundError:
                log.info("Comment was already deleted")
            except TorngitClientError:
                log.warning(
                    "Comment could not be deleted due to client permissions",
                    exc_info=True,
                    extra=dict(
                        repoid=self.repository.repoid,
                        pullid=pullid,
                        commentid=commentid,
                    ),
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": False,
                    "explanation": "no_permissions",
                    "data_received": None,
                }
        try:
            res = async_to_sync(self.repository_service.post_comment)(pullid, message)
            return {
                "notification_attempted": True,
                "notification_successful": True,
                "explanation": None,
                "data_received": {"id": res["id"]},
            }
        except TorngitClientError:
            log.warning(
                "Comment could not be posted due to client permissions",
                exc_info=True,
                extra=dict(
                    repoid=self.repository.repoid, pullid=pullid, commentid=commentid
                ),
            )
            return {
                "notification_attempted": True,
                "notification_successful": False,
                "explanation": "comment_posting_permissions",
                "data_received": None,
            }

    def send_comment_spammy_behavior(self, pullid, commentid, message):
        res = async_to_sync(self.repository_service.post_comment)(pullid, message)
        return {
            "notification_attempted": True,
            "notification_successful": True,
            "explanation": None,
            "data_received": {"id": res["id"]},
        }

    def is_enabled(self) -> bool:
        return bool(self.notifier_yaml_settings) and isinstance(
            self.notifier_yaml_settings, dict
        )

    def build_message(self, comparison: ComparisonProxy) -> list[str]:
        if self.should_use_upgrade_decoration():
            return self._create_upgrade_message(comparison)
        if self.is_processing_upload():
            return self._create_processing_upload_message()
        if self.is_empty_upload():
            return self._create_empty_upload_message()
        if self.should_use_upload_limit_decoration():
            return self._create_reached_upload_limit_message(comparison)
        if comparison.pull.is_first_coverage_pull:
            return self._create_welcome_message()
        pull_dict = comparison.enriched_pull.provider_pull
        return self.create_message(comparison, pull_dict, self.notifier_yaml_settings)

    def should_see_project_coverage_cta(self):
        """
        Why was this check added? We changed our default behavior on 5/1/2024.
        Change explained on issue 1078
        """
        introduction_date = datetime(2024, 5, 1, 0, 0, 0).replace(tzinfo=timezone.utc)

        if (
            not self.repository.private
            and self.repository.owner.createstamp
            and self.repository.owner.createstamp > introduction_date
        ):
            # public repos, only if they signed up after introduction date
            return True

        if (
            not (
                self.repository.owner.plan == BillingPlan.team_monthly.value
                or self.repository.owner.plan == BillingPlan.team_yearly.value
            )
            and self.repository.owner.createstamp
            and self.repository.owner.createstamp > introduction_date
        ):
            # private repos excluding those on team plans, only if they signed up after introduction date
            return True

        return False

    def _create_welcome_message(self):
        welcome_message = [
            "## Welcome to [Codecov](https://codecov.io) :tada:",
            "",
            "Once you merge this PR into your default branch, you're all set! Codecov will compare coverage reports and display results in all future pull requests.",
            "",
            "Thanks for integrating Codecov - We've got you covered :open_umbrella:",
        ]
        project_coverage_cta = [
            ":information_source: You can also turn on [project coverage checks](https://docs.codecov.com/docs/common-recipe-list#set-project-coverage-checks-on-a-pull-request) "
            "and [project coverage reporting on Pull Request comment](https://docs.codecov.com/docs/common-recipe-list#show-project-coverage-changes-on-the-pull-request-comment)",
            "",
        ]

        if self.should_see_project_coverage_cta():
            welcome_message_with_project_coverage_cta = (
                welcome_message[0:4] + project_coverage_cta + welcome_message[4:]
            )
            return welcome_message_with_project_coverage_cta

        return welcome_message

    def _create_empty_upload_message(self):
        if self.is_passing_empty_upload():
            return [
                "## Codecov Report",
                ":heavy_check_mark: **No coverage data to report**, because files changed do not require tests or are set to [ignore](https://docs.codecov.com/docs/ignoring-paths#:~:text=You%20can%20use%20the%20top,will%20be%20skipped%20during%20processing.) ",
            ]
        if self.is_failing_empty_upload():
            return [
                "## Codecov Report",
                "This is an empty upload",
                "Files changed in this PR are testable or aren't ignored by Codecov, please run your tests and upload coverage. If you wish to ignore these files, please visit our [ignoring paths docs](https://docs.codecov.com/docs/ignoring-paths).",
            ]

    def _create_reached_upload_limit_message(self, comparison: ComparisonProxy):
        db_pull = comparison.enriched_pull.database_pull
        links = {"plan_url": get_plan_url(db_pull)}
        return [
            f"## [Codecov]({links['plan_url']}) upload limit reached :warning:",
            f"This org is currently on the free Basic Plan; which includes 250 free private repo uploads each rolling month.\
                 This limit has been reached and additional reports cannot be generated. For unlimited uploads,\
                      upgrade to our [pro plan]({links['plan_url']}).",
            "",
            "**Do you have questions or need help?** Connect with our sales team today at ` sales@codecov.io `",
        ]

    def _create_upgrade_message(self, comparison: ComparisonProxy):
        db_pull = comparison.enriched_pull.database_pull
        links = {
            "members_url_cloud": get_members_url(db_pull),
            "members_url_self_hosted": get_members_url(db_pull),
        }
        author_username = comparison.enriched_pull.provider_pull["author"].get(
            "username"
        )
        if not requires_license():
            return [
                f"The author of this PR, {author_username}, is not an activated member of this organization on Codecov.",
                f"Please [activate this user on Codecov]({links['members_url_cloud']}) to display this PR comment.",
                "Coverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.",
                "Please don't hesitate to email us at support@codecov.io with any questions.",
            ]
        else:
            return [
                f"The author of this PR, {author_username}, is not activated in your Codecov Self-Hosted installation.",
                f"Please [activate this user]({links['members_url_self_hosted']}) to display this PR comment.",
                "Coverage data is still being uploaded to Codecov Self-Hosted for the purposes of overall coverage calculations.",
                "Please contact your Codecov On-Premises installation administrator with any questions.",
            ]

    def _create_processing_upload_message(self):
        return [
            "We're currently processing your upload.  This comment will be updated when the results are available.",
        ]
