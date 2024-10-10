import logging

from shared.torngit.exceptions import TorngitClientError

from services.comparison import ComparisonProxy
from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    NotificationResult,
)

log = logging.getLogger(__name__)


class ChecksWithFallback(AbstractBaseNotifier):
    """
    This class attempts to notify using Github Checks and has the ability of falling back
    to commit_status in the event of users not having enough permissons to use checks.

    Note: This class is not meant to store results.
    """

    def __init__(
        self,
        checks_notifier: AbstractBaseNotifier,
        status_notifier: AbstractBaseNotifier,
    ):
        self._checks_notifier = checks_notifier
        self._status_notifier = status_notifier
        self._decoration_type = checks_notifier.decoration_type
        self._title = checks_notifier.title
        self._name = f"{checks_notifier.name}-with-fallback"
        self._notification_type = checks_notifier.notification_type

    def is_enabled(self):
        return self._checks_notifier.is_enabled() or self._status_notifier.is_enabled()

    @property
    def name(self):
        return self._name

    @property
    def title(self):
        return self._title

    @property
    def notification_type(self):
        return self._notification_type

    @property
    def decoration_type(self):
        return self._decoration_type

    def store_results(self, comparison: ComparisonProxy, result: NotificationResult):
        pass

    def notify(self, comparison: ComparisonProxy) -> NotificationResult:
        try:
            res = self._checks_notifier.notify(comparison)
            if not res.notification_successful and (
                res.explanation == "no_pull_request"
                or res.explanation == "pull_request_not_in_provider"
                or res.explanation == "pull_request_closed"
                or res.explanation == "preexisting_commit_status"
            ):
                log.info(
                    "Couldn't use checks notifier, falling back to status notifiers",
                    extra=dict(
                        notifier=self._checks_notifier.name,
                        repoid=comparison.head.commit.repoid,
                        notifier_title=self._checks_notifier.title,
                        commit=comparison.head.commit,
                        explanation=res.explanation,
                    ),
                )
                res = self._status_notifier.notify(comparison)
            return res
        except TorngitClientError as e:
            if e.code == 403:
                log.info(
                    "Checks notifier failed due to torngit error, falling back to status notifiers",
                    extra=dict(
                        notifier=self._checks_notifier.name,
                        repoid=comparison.head.commit.repoid,
                        notifier_title=self._checks_notifier.title,
                        commit=comparison.head.commit,
                    ),
                )
                return self._status_notifier.notify(comparison)
            raise e
