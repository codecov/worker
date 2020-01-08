from decimal import Decimal

from services.notification.notifiers.base import Comparison
from services.yaml.reader import round_number
from services.notification.notifiers.status.base import StatusNotifier


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
            target_coverage = Decimal(str(self.notifier_yaml_settings.get('target')).replace('%', ''))
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
