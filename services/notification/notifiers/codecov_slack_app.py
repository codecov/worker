import json
import os

from services.notification.notifiers.generics import StandardNotifier

import requests
from services.notification.notifiers.base import NotificationResult
from database.enums import Notification
from services.notification.notifiers.generics import (
    Comparison,
)

CODECOV_INTERNAL_TOKEN = os.getenv("CODECOV_INTERNAL_TOKEN", "not found")

class CodecovSlackAppNotifier(StandardNotifier):
    @property
    def notification_type(self) -> Notification: # will need if we want to store_result
        return Notification.codecov_slack_app

    def is_enabled(self) -> bool:
        return True
    
    async def notify(self, comparison: Comparison, **extra_data) -> NotificationResult:        
        request_url = "http://slack.codecov.io/notify/" 
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {CODECOV_INTERNAL_TOKEN}",
        }

        compare_dict = self.generate_compare_dict(comparison)
        compare_dict["coverage"] = str(compare_dict["coverage"])
        
        data = {
            "repository": self.repository.name,
            "owner": self.repository.owner.name,
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