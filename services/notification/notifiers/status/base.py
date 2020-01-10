import logging

from helpers.match import match
from services.notification.notifiers.base import (
    AbstractBaseNotifier, Comparison, NotificationResult
)
from services.repository import get_repo_provider_service
from services.urls import get_commit_url, get_compare_url
from services.yaml.reader import get_paths_from_flags


log = logging.getLogger(__name__)


class StatusNotifier(AbstractBaseNotifier):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._repository_service = None

    def is_enabled(self):
        return True

    @property
    def name(self):
        return f"status-{self.context}"

    async def build_payload(comparison):
        raise NotImplementedError()

    def can_we_set_this_status(self, comparison):
        head = comparison.head.commit
        pull = comparison.pull
        if (self.notifier_yaml_settings.get('only_pulls') or self.notifier_yaml_settings.get('base') == 'pr') and not pull:
            return False
        if not match(self.notifier_yaml_settings.get('branches'), head.branch):
            return False
        return True

    async def get_diff(self, comparison: Comparison):
        repository_service = self.repository_service
        head = comparison.head.commit
        base = comparison.base.commit
        if base is None:
            return None
        pull_diff = await repository_service.get_compare(base.commitid, head.commitid, with_commits=False)
        return pull_diff['diff']

    @property
    def repository_service(self):
        if not self._repository_service:
            self._repository_service = get_repo_provider_service(self.repository)
        return self._repository_service

    def get_notifier_filters(self):
        return dict(
            paths=set(
                get_paths_from_flags(self.current_yaml, self.notifier_yaml_settings.get('flags')) +
                (self.notifier_yaml_settings.get('paths') or [])
            ),
            flags=self.notifier_yaml_settings.get('flags')
        )

    async def notify(self, comparison: Comparison):
        if not self.can_we_set_this_status(comparison):
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation='not_fit_criteria',
                data_sent=None
            )
        _filters = self.get_notifier_filters()
        base_full_commit = comparison.base
        with comparison.head.report.filter(**_filters):
            with (base_full_commit.report.filter(**_filters) if (comparison.has_base_report() is not None) else WithNone()):
                payload = await self.build_payload(comparison)
        commit_url = get_commit_url(comparison.head.commit)
        pull_url = get_compare_url(comparison.base.commit, comparison.head.commit)
        payload['url'] = pull_url if comparison.pull and self.notifier_yaml_settings.get('base') in ('pr', 'auto', None) else commit_url
        return await self.send_notification(comparison, payload)

    async def status_already_exists(self, comparison, title, state, description):
        head = comparison.head.commit
        repository_service = self.repository_service
        statuses = await repository_service.get_commit_statuses(head.commitid)
        if statuses:
            exists = statuses.get(title)
            return (
                exists and
                exists['state'] == state and
                exists['description'] == description
            )
        return False

    def get_status_external_name(self):
        status_piece = f'/{self.title}' if self.title != 'default' else ''
        return f'codecov/{self.context}{status_piece}'

    async def send_notification(self, comparison: Comparison, payload):
        title = self.get_status_external_name()
        repository_service = self.repository_service
        head = comparison.head.commit
        head_report = comparison.head.report
        state = payload['state']
        message = payload['message']
        url = payload['url']
        if not await self.status_already_exists(comparison, title, state, message):
            state = 'success' if self.notifier_yaml_settings.get('informational') else state
            res = await repository_service.set_commit_status(
                commit=head.commitid,
                status=state,
                context=title,
                coverage=float(head_report.totals.coverage),
                description=message,
                url=url
            )
            notification_result = {
                'title': title,
                'state': state,
                'message': message,
            }
            return NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                explanation=None,
                data_sent=notification_result,
                data_received={'id': res.get('id', 'NO_ID')}
            )
        else:
            log.info(
                'Status already set',
                extra=dict(
                    context=title,
                    description=message,
                    state=state
                )
            )
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation='already_done',
                data_sent={'title': title, 'state': state, 'message': message}
            )
