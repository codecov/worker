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
from services.notification.notifiers.generics import Comparison
from services.urls import get_commit_url, get_pull_url
from services.yaml.reader import round_number

CODECOV_INTERNAL_TOKEN = os.environ.get("CODECOV_INTERNAL_TOKEN")
CODECOV_SLACK_APP = os.environ.get("CODECOV_SLACK_APP")

class CodecovSlackAppNotifier(AbstractBaseNotifier):
    name = "codecov-slack-app"

    @property
    def notification_type(self) -> Notification:
        return Notification.codecov_slack_app

    def is_enabled(self) -> bool:
        return True

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
        base_full_commit = comparison.base
        if comparison.has_base_report():
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
                comparison.base.commit if comparison.base else None
            ),
            "head_totals_c": comparison.head.report.totals.coverage,
        }

    async def notify(self, comparison: Comparison, **extra_data) -> NotificationResult:
        request_url = f"{CODECOV_SLACK_APP}/notify"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {CODECOV_INTERNAL_TOKEN}",
        }

        compare_dict = self.build_payload(comparison)

        data = {
            "repository": self.repository.name,
            "owner": self.repository.owner.username,
            "comparison": compare_dict,
        }
        response = requests.post(request_url, headers=headers, data=json.dumps(data))

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
