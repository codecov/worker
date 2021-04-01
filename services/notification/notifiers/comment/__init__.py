import logging
from typing import Any, Mapping, List

from shared.torngit.exceptions import (
    TorngitObjectNotFoundError,
    TorngitClientError,
    TorngitServerFailureError,
)

from database.enums import Notification
from services.notification.notifiers.base import (
    NotificationResult,
    AbstractBaseNotifier,
)
from services.notification.types import Comparison
from helpers.metrics import metrics
from services.repository import get_repo_provider_service
from services.urls import get_org_account_url

from services.notification.notifiers.mixins.message import MessageMixin

from services.license import requires_license

log = logging.getLogger(__name__)


class CommentNotifier(MessageMixin, AbstractBaseNotifier):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._repository_service = None

    @property
    def repository_service(self):
        if not self._repository_service:
            self._repository_service = get_repo_provider_service(self.repository)
        return self._repository_service

    def store_results(self, comparison: Comparison, result: NotificationResult):
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

    async def get_diff(self, comparison: Comparison):
        return await comparison.get_diff()

    async def has_enough_changes(self, comparison):
        diff = await comparison.get_diff()
        changes = await comparison.get_changes()
        if changes:
            return True
        res = comparison.head.report.calculate_diff(diff)
        if res is not None and res["general"].lines > 0:
            return True
        return False

    async def notify(self, comparison: Comparison, **extra_data) -> NotificationResult:
        if comparison.pull is None:
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="no_pull_request",
                data_sent=None,
                data_received=None,
            )
        if (
            comparison.enriched_pull is None
            or comparison.enriched_pull.provider_pull is None
        ):
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_not_in_provider",
                data_sent=None,
                data_received=None,
            )
        if comparison.pull.state != "open":
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_closed",
                data_sent=None,
                data_received=None,
            )
        if comparison.pull.head != comparison.head.commit.commitid:
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_head_does_not_match",
                data_sent=None,
                data_received=None,
            )
        if self.notifier_yaml_settings.get("after_n_builds") is not None:
            n_builds_present = len(comparison.head.report.sessions)
            if n_builds_present < self.notifier_yaml_settings.get("after_n_builds"):
                return NotificationResult(
                    notification_attempted=False,
                    notification_successful=None,
                    explanation="not_enough_builds",
                    data_sent=None,
                    data_received=None,
                )
        pull = comparison.pull
        if self.notifier_yaml_settings.get("require_changes"):
            if not (await self.has_enough_changes(comparison)):
                data_received = None
                if pull.commentid is not None:
                    log.info(
                        "Deleting comment because there are not enough changes according to YAML",
                        extra=dict(
                            repoid=pull.repoid,
                            pullid=pull.pullid,
                            commentid=pull.commentid,
                        ),
                    )
                    try:
                        await self.repository_service.delete_comment(
                            pull.pullid, pull.commentid
                        )
                        data_received = {"deleted_comment": True}
                    except TorngitClientError:
                        log.warning(
                            "Comment could not be deleted due to client permissions",
                            exc_info=True,
                        )
                        data_received = {"deleted_comment": False}
                return NotificationResult(
                    notification_attempted=False,
                    notification_successful=None,
                    explanation="changes_required",
                    data_sent=None,
                    data_received=data_received,
                )
        try:
            with metrics.timer(
                "worker.services.notifications.notifiers.comment.build_message"
            ):
                message = await self.build_message(comparison)
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
                notification_successful=None,
                explanation="unable_build_message",
                data_sent=None,
                data_received=None,
            )
        data = {"message": message, "commentid": pull.commentid, "pullid": pull.pullid}
        try:
            with metrics.timer(
                "worker.services.notifications.notifiers.comment.send_notifications"
            ):
                return await self.send_actual_notification(data)
        except TorngitServerFailureError:
            log.warning(
                "Unable to send comments because the provider server was not reachable or errored",
                extra=dict(service=self.repository.service,),
                exc_info=True,
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="provider_issue",
                data_sent=data,
                data_received=None,
            )

    async def send_actual_notification(self, data: Mapping[str, Any]):
        message = "\n".join(data["message"])
        behavior = self.notifier_yaml_settings.get("behavior", "default")
        if behavior == "default":
            res = await self.send_comment_default_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "once":
            res = await self.send_comment_once_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "new":
            res = await self.send_comment_new_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "spammy":
            res = await self.send_comment_spammy_behavior(
                data["pullid"], data["commentid"], message
            )
        return NotificationResult(
            notification_attempted=res["notification_attempted"],
            notification_successful=res["notification_successful"],
            explanation=res["explanation"],
            data_sent=data,
            data_received=res["data_received"],
        )

    async def send_comment_default_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                res = await self.repository_service.edit_comment(
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
            res = await self.repository_service.post_comment(pullid, message)
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

    async def send_comment_once_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                res = await self.repository_service.edit_comment(
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
        res = await self.repository_service.post_comment(pullid, message)
        return {
            "notification_attempted": True,
            "notification_successful": True,
            "explanation": None,
            "data_received": {"id": res["id"]},
        }

    async def send_comment_new_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                await self.repository_service.delete_comment(pullid, commentid)
            except TorngitObjectNotFoundError:
                log.info("Comment was already deleted")
            except TorngitClientError:
                log.warning(
                    "Comment could not be deleted due to client permissions",
                    exc_info=True,
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": False,
                    "explanation": "no_permissions",
                    "data_received": None,
                }
        try:
            res = await self.repository_service.post_comment(pullid, message)
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

    async def send_comment_spammy_behavior(self, pullid, commentid, message):
        res = await self.repository_service.post_comment(pullid, message)
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

    async def build_message(self, comparison: Comparison) -> List[str]:
        if self.should_use_upgrade_decoration():
            return self._create_upgrade_message(comparison)
        pull_dict = comparison.enriched_pull.provider_pull
        return await self.create_message(
            comparison, pull_dict, self.notifier_yaml_settings
        )

    def _create_upgrade_message(self, comparison):
        db_pull = comparison.enriched_pull.database_pull
        links = {
            "org_account": get_org_account_url(db_pull),
        }
        author_username = comparison.enriched_pull.provider_pull["author"].get(
            "username"
        )
        if not requires_license():
            return [
                f"The author of this PR, {author_username}, is not an activated member of this organization on Codecov.",
                f"Please [activate this user on Codecov]({links['org_account']}/users) to display this PR comment.",
                f"Coverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.",
                f"Please don't hesitate to email us at success@codecov.io with any questions.",
            ]
        else:
            return [
                f"The author of this PR, {author_username}, is not activated in your Codecov Self-Hosted installation.",
                f"Please [activate this user]({links['org_account']}/users) to display this PR comment.",
                f"Coverage data is still being uploaded to Codecov Self-Hosted for the purposes of overall coverage calculations.",
                f"Please contact your Codecov On-Premises installation administrator with any questions.",
            ]
