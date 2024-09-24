import json
import os
from decimal import Decimal

import requests

from database.enums import Notification
from database.models import Commit
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)
from services.notification.notifiers.generics import Comparison, EnhancedJSONEncoder
from services.urls import get_commit_url, get_pull_url
from services.yaml.reader import round_number

CODECOV_INTERNAL_TOKEN = os.environ.get("CODECOV_INTERNAL_TOKEN")
CODECOV_SLACK_APP_URL = os.environ.get("CODECOV_SLACK_APP_URL")


class CodecovSlackAppNotifier(AbstractBaseNotifier):
    name = "codecov-slack-app"

    @property
    def notification_type(self) -> Notification:
        return Notification.codecov_slack_app

    def is_enabled(self) -> bool:
        # if yaml settings are a dict, then check the enabled key and return that
        # the enabled field should always exist if the yaml settings are a dict because otherwise it would fail the validation

        # else if the yaml settings is a boolean then just return that

        # in any case, self.notifier_yaml_settings should either be a bool or a dict always and should never be None
        if isinstance(self.notifier_yaml_settings, dict):
            return self.notifier_yaml_settings.get("enabled", False)
        elif isinstance(self.notifier_yaml_settings, bool):
            return self.notifier_yaml_settings

    def store_results(self, comparison: Comparison, result: NotificationResult):
        pass

    def serialize_commit(self, commit: Commit):
        if not commit:
            return None
        return {
            "commitid": commit.commitid,
            "branch": commit.branch,
            "message": commit.message,
            "author": commit.author.username if commit.author else None,
            "timestamp": commit.timestamp.isoformat() if commit.timestamp else None,
            "ci_passed": commit.ci_passed,
            "totals": commit.totals,
            "pull": commit.pullid,
        }

    def build_payload(self, comparison: Comparison):
        head_full_commit = comparison.head
        base_full_commit = comparison.project_coverage_base
        if comparison.has_project_coverage_base_report():
            difference = None
            head_report_coverage = head_full_commit.report.totals.coverage
            base_report_coverage = base_full_commit.report.totals.coverage
            if head_report_coverage is not None and base_report_coverage is not None:
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
            "coverage": str(round_number(self.current_yaml, difference))
            if difference is not None
            else None,
            "notation": notation,
            "head_commit": self.serialize_commit(
                comparison.head.commit if comparison.head else None
            ),
            "base_commit": self.serialize_commit(
                comparison.project_coverage_base.commit
                if comparison.project_coverage_base
                else None
            ),
            "head_totals_c": str(comparison.head.report.totals.coverage),
        }

    def notify(self, comparison: Comparison, **extra_data) -> NotificationResult:
        request_url = f"{CODECOV_SLACK_APP_URL}/notify"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CODECOV_INTERNAL_TOKEN}",
        }

        compare_dict = self.build_payload(comparison)
        data = {
            "repository": self.repository.name,
            "owner": self.repository.owner.username,
            "comparison": compare_dict,
        }
        response = requests.post(
            request_url, headers=headers, data=json.dumps(data, cls=EnhancedJSONEncoder)
        )

        if response.status_code == 200:
            return NotificationResult(
                data_sent=data,
                notification_attempted=True,
                notification_successful=True,
                explanation="Successfully notified slack app",
            )
        else:
            return NotificationResult(
                data_sent=data,
                notification_attempted=True,
                notification_successful=False,
                explanation=f"Failed to notify slack app\nError {response.status_code}: {response.reason}.",
            )
