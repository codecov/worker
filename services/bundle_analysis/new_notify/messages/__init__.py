from abc import ABC, abstractmethod

from services.bundle_analysis.new_notify.contexts import (
    BaseBundleAnalysisNotificationContext,
)
from services.notification.notifiers.base import NotificationResult


class MessageStrategyInterface(ABC):
    @abstractmethod
    def build_message(
        self, context: BaseBundleAnalysisNotificationContext
    ) -> str | bytes:
        pass

    @abstractmethod
    async def send_message(
        self, context: BaseBundleAnalysisNotificationContext, message: str | bytes
    ) -> NotificationResult:
        pass
