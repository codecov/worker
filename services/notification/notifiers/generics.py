import json
import logging
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
import sentry_sdk
from shared.config import get_config

from helpers.match import match
from helpers.metrics import metrics
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)
from services.repository import get_repo_provider_service
from services.urls import get_commit_url, get_pull_url
from services.yaml.reader import get_paths_from_flags, round_number

log = logging.getLogger(__name__)


class StandardNotifier(AbstractBaseNotifier):
    """
    This class is our standard notifier. It assumes and does the following:

    - Ensure that the notifier has a valid `url` to be used
    - Ensure that the `url` base is enabled on site-wide settings
    - Check that the current branch is inside the list of enabled branches
    - Filters the reports according to the given paths and flags
    - Check that the threshold of the webhook is satisfied on this comparison
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._repository_service = None

    @property
    def repository_service(self):
        if not self._repository_service:
            self._repository_service = get_repo_provider_service(
                self.repository, installation_name_to_use=self.gh_installation_name
            )
        return self._repository_service

    def store_results(self, comparison: ComparisonProxy, result: NotificationResult):
        pass

    @property
    def name(self):
        return self.__class__.__name__

    def is_enabled(self) -> bool:
        if not bool(self.site_settings):
            log.info(
                "Not notifying on %s, because it is not enabled on site-level settings",
                self.name,
            )
            return False
        if not self.notifier_yaml_settings.get("url"):
            log.warning("Not notifying because webhook had no url")
            return False
        parsed_url = urlparse(self.notifier_yaml_settings.get("url"))
        if (
            isinstance(self.site_settings, list)
            and parsed_url.netloc not in self.site_settings
        ):
            log.warning("Not notifying because url not permitted by site settings")
            return False
        return True

    def should_notify_comparison(self, comparison: Comparison) -> bool:
        head_full_commit = comparison.head
        if not match(
            self.notifier_yaml_settings.get("branches"), head_full_commit.commit.branch
        ):
            log.warning(
                "Not notifying because branch not in expected branches",
                extra=dict(
                    commit=head_full_commit.commit.commitid,
                    repoid=head_full_commit.commit.repoid,
                    current_branch=head_full_commit.commit.branch,
                    branch_patterns=self.notifier_yaml_settings.get("branches"),
                ),
            )
            return False
        if not self.is_above_threshold(comparison):
            return False
        return True

    @sentry_sdk.trace
    def notify(self, comparison: ComparisonProxy) -> NotificationResult:
        filtered_comparison = comparison.get_filtered_comparison(
            **self.get_notifier_filters()
        )
        if self.should_notify_comparison(filtered_comparison):
            result = self.do_notify(filtered_comparison)
        else:
            result = NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="Did not fit criteria",
                data_sent=None,
            )
        return result

    def get_notifier_filters(self) -> dict:
        flag_list = self.notifier_yaml_settings.get("flags") or []
        return dict(
            path_patterns=set(
                get_paths_from_flags(self.current_yaml, flag_list)
                + (self.notifier_yaml_settings.get("paths") or [])
            ),
            flags=flag_list,
        )

    def do_notify(self, comparison: Comparison) -> NotificationResult:
        data = self.build_payload(comparison)
        result = self.send_actual_notification(data)
        return NotificationResult(
            notification_attempted=result["notification_attempted"],
            notification_successful=result["notification_successful"],
            explanation=result["explanation"],
            data_sent=data,
        )

    def is_above_threshold(self, comparison: Comparison):
        head_full_commit = comparison.head
        base_full_commit = comparison.project_coverage_base
        threshold = self.notifier_yaml_settings.get("threshold")
        if threshold is None:
            return True
        if not comparison.has_project_coverage_base_report():
            log.info(
                "Cannot compare commits because base commit does not have a report",
                extra=dict(
                    commit=head_full_commit.commit.commitid,
                    base_commit=base_full_commit.commit.commitid
                    if base_full_commit.commit
                    else None,
                ),
            )
            return False
        if (
            base_full_commit.report.totals.coverage is None
            or head_full_commit.report.totals.coverage is None
        ):
            log.info(
                "Cannot compare commits because either base or head commit has no coverage information",
                extra=dict(
                    commit=head_full_commit.commit.commitid,
                    base_commit=base_full_commit.commit.commitid
                    if base_full_commit.commit
                    else None,
                ),
            )
            return False
        diff_coverage = Decimal(head_full_commit.report.totals.coverage) - Decimal(
            base_full_commit.report.totals.coverage
        )
        rounded_coverage = round_number(self.current_yaml, diff_coverage)
        return rounded_coverage >= threshold

    def generate_compare_dict(self, comparison: Comparison):
        head_full_commit = comparison.head
        base_full_commit = comparison.project_coverage_base
        if comparison.has_project_coverage_base_report():
            difference = Decimal(head_full_commit.report.totals.coverage) - Decimal(
                base_full_commit.report.totals.coverage
            )
            message = (
                "no change"
                if difference == 0
                else "increased"
                if difference > 0
                else "decreased"
            )
            notation = "" if difference == 0 else "+" if difference > 0 else "-"
            comparison_url = (
                get_pull_url(comparison.pull)
                if comparison.pull
                else get_commit_url(comparison.head.commit)
            )
        else:
            difference = None
            message = "unknown"
            notation = ""
            comparison_url = None
        return {
            "url": comparison_url,
            "message": message,
            "coverage": round_number(self.current_yaml, difference)
            if difference is not None
            else None,
            "notation": notation,
        }

    def generate_message(self, comparison: Comparison):
        if self.notifier_yaml_settings.get("message"):
            return self.notifier_yaml_settings.get("message")
        commit = comparison.head.commit
        comparison_string = ""
        if comparison.has_project_coverage_base_report():
            compare = self.generate_compare_dict(comparison)
            comparison_string = self.COMPARISON_STRING.format(
                compare_message=compare["message"],
                compare_url=compare["url"],
                compare_notation=compare["notation"],
                compare_coverage=compare["coverage"],
            )
        return self.BASE_MESSAGE.format(
            head_url=get_commit_url(commit),
            owner_username=commit.repository.owner.username,
            repo_name=commit.repository.name,
            comparison_string=comparison_string,
            head_branch=commit.branch,
            head_totals_c=comparison.head.report.totals.coverage,
            head_short_commitid=commit.commitid[:7],
        )


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


class RequestsYamlBasedNotifier(StandardNotifier):
    """
    This class is a small implementation detail for using `requests` package to communicate with
        the server we want to notify
    """

    json_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Codecov",
    }

    def send_actual_notification(self, data: Mapping[str, Any]):
        _timeouts = get_config("setup", "http", "timeouts", "external", default=10)
        kwargs = dict(timeout=_timeouts, headers=self.json_headers)
        try:
            with metrics.timer(
                f"worker.services.notifications.notifiers.{self.name}.actual_connection"
            ):
                with httpx.Client() as client:
                    res = client.post(
                        url=self.notifier_yaml_settings["url"],
                        data=json.dumps(data, cls=EnhancedJSONEncoder),
                        **kwargs,
                    )
            return {
                "notification_attempted": True,
                "notification_successful": res.status_code < 400,
                "explanation": None if res.status_code else res.message,
            }
        except httpx.HTTPError:
            log.warning(
                "Unable to send notification to server due to a connection error",
                exc_info=True,
            )
            return {
                "notification_attempted": True,
                "notification_successful": False,
                "explanation": "connection_issue",
            }
