from abc import ABC, abstractmethod

from services.bundle_analysis.notify.contexts import (
    BaseBundleAnalysisNotificationContext,
)
from services.notification.notifiers.base import NotificationResult


class MessageStrategyInterface(ABC):
    @abstractmethod
    def build_message(
        self, context: BaseBundleAnalysisNotificationContext
    ) -> str | bytes:
        """Builds the message to be sent using the `context` information"""
        pass

    @abstractmethod
    async def send_message(
        self, context: BaseBundleAnalysisNotificationContext, message: str | bytes
    ) -> NotificationResult:
        pass
