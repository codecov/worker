import logging
from contextlib import nullcontext
from typing import Dict

from shared.config import get_config
from shared.torngit.exceptions import TorngitClientError, TorngitError
from shared.utils.sessions import SessionType

from helpers.cache import DEFAULT_TTL, NO_VALUE, cache, make_hash_sha256
from helpers.match import match
from helpers.metrics import metrics
from services.comparison import ComparisonProxy
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    Comparison,
    NotificationResult,
)
from services.repository import get_repo_provider_service
from services.urls import get_commit_url, get_pull_url
from services.yaml import read_yaml_field
from services.yaml.reader import get_paths_from_flags

log = logging.getLogger(__name__)


class StatusNotifier(AbstractBaseNotifier):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._repository_service = None

    def is_enabled(self) -> bool:
        return True

    def store_results(self, comparison: Comparison, result: NotificationResult) -> bool:
        pass

    @property
    def name(self):
        return f"status-{self.context}"

    async def build_payload(self, comparison) -> Dict[str, str]:
        raise NotImplementedError()

    def get_upgrade_message(self) -> str:
        # TODO: this is the message in the PR author billing spec but maybe we should add the actual username?
        return "Please activate this user to display a detailed status check"

    def get_status_check_for_empty_upload(self):
        if self.is_passing_empty_upload():
            return ("success", "Non-testable files changed.")

        if self.is_failing_empty_upload():
            return ("failure", "Testable files changed")

    def can_we_set_this_status(self, comparison) -> bool:
        head = comparison.head.commit
        pull = comparison.pull
        if (
            self.notifier_yaml_settings.get("only_pulls")
            or self.notifier_yaml_settings.get("base") == "pr"
        ) and not pull:
            return False
        if not match(self.notifier_yaml_settings.get("branches"), head.branch):
            return False
        return True

    def determine_status_check_behavior_to_apply(
        self, comparison, field_name
    ) -> str or None:
        """
        Used for fields that can be set at the global level for all checks in "default_rules", or at the component level for an individual check.
        For more context, see https://docs.codecov.io/docs/commit-status#default_rules
        """
        # Get the component level setting, if one is specified
        component_behavior = self.notifier_yaml_settings.get(field_name)
        # Get the value set at the global level via the default_rules key. This can be 'None' if no value was provided.
        # If provided, this is populated either by the YAML file directly or by the defaults set in 'shared'.
        default_rules_behavior = read_yaml_field(
            self.current_yaml, ("coverage", "status", "default_rules", field_name)
        )

        behavior_to_apply = (
            component_behavior
            if component_behavior is not None
            else default_rules_behavior
        )

        return behavior_to_apply

    def flag_coverage_was_uploaded(self, comparison) -> bool:
        """
        Indicates whether coverage was uploaded for any of the flags on this status check.
        If there are no flags on the status check, this will return true.
        If there are multiple flags on the status check, this will return true if at least one of them has uploaded coverage.
        """

        flags_included_in_status_check = set(
            self.notifier_yaml_settings.get("flags") or []
        )
        if not flags_included_in_status_check:
            return True
        report_uploaded_flags = comparison.head.report.get_uploaded_flags()
        return (
            len(report_uploaded_flags.intersection(flags_included_in_status_check)) > 0
        )

    async def get_diff(self, comparison: Comparison):
        return await comparison.get_diff()

    @property
    def repository_service(self):
        if not self._repository_service:
            self._repository_service = get_repo_provider_service(self.repository)
        return self._repository_service

    def get_notifier_filters(self) -> dict:
        flag_list = self.notifier_yaml_settings.get("flags") or []
        return dict(
            path_patterns=set(
                get_paths_from_flags(self.current_yaml, flag_list)
                + (self.notifier_yaml_settings.get("paths") or [])
            ),
            flags=flag_list,
        )

    def required_builds(self, comparison: Comparison) -> bool:
        flags = self.notifier_yaml_settings.get("flags") or []
        head_report = comparison.head.report

        for flag in flags:
            flag_configuration = self.current_yaml.get_flag_configuration(flag)
            if flag_configuration and head_report and head_report.sessions:
                number_of_occ = 0
                for sid, session in head_report.sessions.items():
                    if session.flags and flag in session.flags:
                        number_of_occ += 1
                needed_builds = flag_configuration.get("after_n_builds", 0)
                if number_of_occ < needed_builds:
                    log.info(
                        "Flag needs more builds to send status check",
                        extra=dict(
                            flag=flag,
                            needed_builds=needed_builds,
                            number_of_occ=number_of_occ,
                            repoid=comparison.head.commit.repoid,
                            commit=comparison.head.commit.commitid,
                        ),
                    )
                    return False
        return True

    async def notify(self, comparison: Comparison):
        payload = None
        if not self.can_we_set_this_status(comparison):
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="not_fit_criteria",
                data_sent=None,
            )
        if not self.required_builds(comparison):
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="need_more_builds",
                data_sent=None,
            )
        # Filter the coverage report based on fields in this notification's YAML settings
        # e.g. if "paths" is specified, exclude the coverage not on those paths
        try:
            # If flag coverage wasn't uploaded, apply the appropriate behavior
            flag_coverage_not_uploaded_behavior = (
                self.determine_status_check_behavior_to_apply(
                    comparison, "flag_coverage_not_uploaded_behavior"
                )
            )
            if not comparison.has_head_report():
                payload = await self.build_payload(comparison)
            elif (
                flag_coverage_not_uploaded_behavior == "exclude"
                and not self.flag_coverage_was_uploaded(comparison)
            ):
                return NotificationResult(
                    notification_attempted=False,
                    notification_successful=None,
                    explanation="exclude_flag_coverage_not_uploaded_checks",
                    data_sent=None,
                    data_received=None,
                )
            elif (
                flag_coverage_not_uploaded_behavior == "pass"
                and not self.flag_coverage_was_uploaded(comparison)
            ):
                filtered_comparison = comparison.get_filtered_comparison(
                    **self.get_notifier_filters()
                )
                payload = await self.build_payload(filtered_comparison)
                payload["state"] = "success"
                payload["message"] = (
                    payload["message"]
                    + " [Auto passed due to carriedforward or missing coverage]"
                )
            else:
                filtered_comparison = comparison.get_filtered_comparison(
                    **self.get_notifier_filters()
                )
                payload = await self.build_payload(filtered_comparison)
            if comparison.pull:
                payload["url"] = get_pull_url(comparison.pull)
            else:
                payload["url"] = get_commit_url(comparison.head.commit)

            return await self.maybe_send_notification(comparison, payload)
        except TorngitClientError:
            log.warning(
                "Unable to send status notification to user due to a client-side error",
                exc_info=True,
                extra=dict(
                    repoid=comparison.head.commit.repoid,
                    commit=comparison.head.commit.commitid,
                    notifier_name=self.name,
                ),
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="client_side_error_provider",
                data_sent=payload,
            )
        except TorngitError:
            log.warning(
                "Unable to send status notification to user due to an unexpected error",
                exc_info=True,
                extra=dict(
                    repoid=comparison.head.commit.repoid,
                    commit=comparison.head.commit.commitid,
                    notifier_name=self.name,
                ),
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="server_side_error_provider",
                data_sent=payload,
            )

    async def status_already_exists(
        self, comparison: ComparisonProxy, title, state, description
    ) -> bool:
        statuses = await comparison.get_existing_statuses()
        if statuses:
            exists = statuses.get(title)
            return (
                exists
                and exists["state"] == state
                and exists["description"] == description
            )
        return False

    def get_status_external_name(self) -> str:
        status_piece = f"/{self.title}" if self.title != "default" else ""
        return f"codecov/{self.context}{status_piece}"

    async def maybe_send_notification(
        self, comparison: Comparison, payload: dict
    ) -> NotificationResult:
        base_commit = comparison.base.commit if comparison.base else None
        head_commit = comparison.head.commit if comparison.head else None

        cache_key = make_hash_sha256(
            dict(
                type="status_check_notification",
                repoid=head_commit.repoid,
                base_commitid=base_commit.commitid if base_commit else None,
                head_commitid=head_commit.commitid if head_commit else None,
                notifier_name=self.name,
                notifier_title=self.title,
            )
        )

        last_payload = cache.get_backend().get(cache_key)
        if last_payload is NO_VALUE or last_payload != payload:
            ttl = int(
                get_config("setup", "cache", "send_status_notification", default=600)
            )  # 10 min default
            cache.get_backend().set(cache_key, ttl, payload)
            return await self.send_notification(comparison, payload)
        else:
            log.info(
                "Notification payload unchanged.  Skipping notification.",
                extra=dict(
                    repoid=head_commit.repoid,
                    base_commitid=base_commit.commitid if base_commit else None,
                    head_commitid=head_commit.commitid if head_commit else None,
                    notifier_name=self.name,
                    notifier_title=self.title,
                ),
            )
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="payload_unchanged",
                data_sent=None,
            )

    async def send_notification(self, comparison: Comparison, payload):
        title = self.get_status_external_name()
        repository_service = self.repository_service
        head = comparison.head.commit
        head_report = comparison.head.report
        state = payload["state"]
        message = payload["message"]
        url = payload["url"]
        if not await self.status_already_exists(comparison, title, state, message):
            state = (
                "success" if self.notifier_yaml_settings.get("informational") else state
            )

            notification_result_data_sent = {
                "title": title,
                "state": state,
                "message": message,
            }
            try:
                with metrics.timer(
                    "worker.services.notifications.notifiers.status.set_commit_status"
                ):
                    res = await repository_service.set_commit_status(
                        commit=head.commitid,
                        status=state,
                        context=title,
                        coverage=float(head_report.totals.coverage)
                        if head_report
                        else 0,
                        description=message,
                        url=url,
                    )
            except TorngitClientError:
                log.warning(
                    "Status not posted because this user can see but not set statuses on this repo",
                    extra=dict(
                        data_sent=notification_result_data_sent,
                        commit=comparison.head.commit.commitid,
                        repoid=comparison.head.commit.repoid,
                    ),
                )
                return NotificationResult(
                    notification_attempted=True,
                    notification_successful=False,
                    explanation="no_write_permission",
                    data_sent=notification_result_data_sent,
                    data_received=None,
                )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation=None,
                data_sent=notification_result_data_sent,
                data_received={"id": res.get("id", "NO_ID")},
            )
        else:
            log.info(
                "Status already set",
                extra=dict(context=title, description=message, state=state),
            )
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="already_done",
                data_sent={"title": title, "state": state, "message": message},
            )
