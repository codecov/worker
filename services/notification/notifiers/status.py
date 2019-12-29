import logging
from decimal import Decimal

from helpers.match import match
from services.notification.changes import get_changes
from services.notification.notifiers.base import AbstractBaseNotifier, Comparison, NotificationResult
from services.repository import get_repo_provider_service
from services.urls import get_commit_url, get_compare_url
from services.yaml.reader import round_number

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

    async def notify(self, comparison: Comparison):
        if not self.can_we_set_this_status(comparison):
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation='not_fit_criteria',
                data_sent=None
            )
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
                data_received={'id': res['id']}
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


class ProjectStatusNotifier(StatusNotifier):

    """

    Attributes:
        context (str): The context

    Possible results
        - 100% remains the same compared to 29320f9
        - 57.42% (+<.01%) compared to 559fe9e
        - 85.65% (target 87%)
        - No report found to compare against

    Not implemented results (yet):
        - Absolute coverage decreased by -{0}% but relative coverage ...
    """

    context = 'project'

    def _get_project_status(self, comparison):
        threshold = Decimal(self.notifier_yaml_settings.get('threshold') or '0.0')
        if self.notifier_yaml_settings.get('target') not in ('auto', None):
            head_coverage = Decimal(comparison.head.report.totals.coverage)
            target_coverage = Decimal(self.notifier_yaml_settings.get('target').replace('%', ''))
            state = 'success' if ((head_coverage + threshold) >= target_coverage) else 'failure'
            head_coverage_str = round_number(self.current_yaml, head_coverage)
            expected_coverage_str = round_number(self.current_yaml, target_coverage)
            message = f"{head_coverage_str}% (target {expected_coverage_str}%"
            return (state, message)
        if comparison.base.report is None:
            state = self.notifier_yaml_settings.get('if_not_found', 'success')
            message = 'No report found to compare against'
            return (state, message)
        target_coverage = Decimal(comparison.base.report.totals.coverage)
        head_coverage = Decimal(comparison.head.report.totals.coverage)
        if head_coverage == target_coverage:
            state = 'success'
            message = f'{head_coverage}% remains the same compared to {comparison.base.commit.commitid[:7]}'
        state = 'success' if head_coverage + threshold >= target_coverage else 'failure'
        change_coverage = round_number(self.current_yaml, head_coverage - target_coverage)
        message = f"{head_coverage}% (+{change_coverage}%) compared to {comparison.base.commit.commitid[:7]}"
        return (state, message)

    async def build_payload(self, comparison: Comparison):
        state, message = self._get_project_status(comparison)
        return {
            'state': state,
            'message': message,
        }


class PatchStatusNotifier(StatusNotifier):

    """This status analyzes the git patch and sees covered lines within it

    Attributes:
        context (str): The context

    Possible results
        - No report found to compare against
        - f'{coverage_str}% of diff hit (within {threshold_str}% threshold of {target_str}%)'
        - {coverage_str}% of diff hit (target {target_str}%)
    """

    context = 'patch'

    async def build_payload(self, comparison: Comparison):
        threshold = Decimal(self.notifier_yaml_settings.get('threshold') or '0.0')
        diff = await self.get_diff(comparison)
        totals = comparison.head.report.apply_diff(diff)
        if self.notifier_yaml_settings.get('target') not in ('auto', None):
            target_coverage = Decimal(self.notifier_yaml_settings.get('target').replace('%', ''))
        else:
            target_coverage = Decimal(comparison.base.report.totals.coverage) if comparison.has_base_report() else None
        if totals and totals.lines > 0:
            coverage = Decimal(totals.coverage)
            if target_coverage is None:
                state = self.notifier_yaml_settings.get('if_not_found', 'success')
                message = 'No report found to compare against'
            else:
                state = 'success' if coverage >= target_coverage else 'failure'
                if state == 'failure' and threshold is not None and coverage >= (target_coverage - threshold):
                    state = 'success'
                    coverage_str = round_number(self.current_yaml, coverage)
                    threshold_str = round_number(self.current_yaml, threshold)
                    target_str = round_number(self.current_yaml, target_coverage)
                    message = f'{coverage_str}% of diff hit (within {threshold_str}% threshold of {target_str}%)'

                else:
                    coverage_str = round_number(self.current_yaml, coverage)
                    target_str = round_number(self.current_yaml, target_coverage)
                    message = f'{coverage_str}% of diff hit (target {target_str}%)'
            return {
                'state': state,
                'message': message
            }
        if comparison.base.commit:
            description = 'Coverage not affected when comparing {0}...{1}'.format(
                comparison.base.commit.commitid[:7], comparison.head.commit.commitid[:7]
            )
        else:
            description = 'Coverage not affected'

        return {
            'state': 'success',
            'message': description
        }


class ChangesStatusNotifier(StatusNotifier):

    """This status analyzes the "unexpected changes" (see services/notification/changes.py
        for a better description) and covered lines within it

    Attributes:
        context (str): The context

    Possible results
        - 'No unexpected coverage changes found.'
        - {0} {1} unexpected coverage changes not visible in diff
        - Unable to determine changes, no report found at pull request base
    """

    context = 'changes'

    def is_a_change_worth_noting(self, change):
        if not change.new and not change.deleted:
            # has totals and not -10m => 10h
            t = change.totals
            if t:
                # new missed||partial lines
                return (t.misses + t.partials) > 0
        return False

    async def build_payload(self, comparison):
        pull = comparison.pull
        if self.notifier_yaml_settings.get('base') in ('auto', None, 'pr') and pull:
            if not comparison.has_base_report():
                description = 'Unable to determine changes, no report found at pull request base'
                state = 'success'
                return {
                    'state': state,
                    'message': description
                }

        # filter changes
        diff_json = await self.get_diff(comparison)
        changes = get_changes(comparison.base.report, comparison.head.report, diff_json)
        if changes:
            changes = list(filter(self.is_a_change_worth_noting, changes))

        # remove new additions
        if changes:
            lpc = len(changes)
            eng = 'files have' if lpc > 1 else 'file has'
            description = '{0} {1} unexpected coverage changes not visible in diff'.format(lpc, eng)
            return {
                'state': 'success' if self.notifier_yaml_settings.get('informational') else 'failure',
                'message': description
            }

        description = 'No unexpected coverage changes found'
        return {
            'state': 'success',
            'message': description
        }
