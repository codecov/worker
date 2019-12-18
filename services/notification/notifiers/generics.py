from typing import Mapping, Any
import logging
from urllib.parse import urlparse
from decimal import Decimal
import requests


from helpers.metrics import metrics
from services.report.match import match
from services.yaml.reader import round_number, get_paths_from_flags
from services.urls import get_compare_url, get_commit_url
from services.notification.notifiers.base import AbstractBaseNotifier
from services.notification.types import Comparison


log = logging.getLogger(__name__)


class WithNone:
    def __enter__(self):
        pass

    def __exit__(self, *args):
        pass


class StandardNotifier(AbstractBaseNotifier):
    """
        This class is our standard notifier. It assumes and does the following:

        - Ensure that the notifier has a valid `url` to be used
        - Ensure that the `url` base is enabled on site-wide settings
        - Check that the current branch is inside the list of enabled branches
        - Filters the reports according to the given paths and flags
        - Check that the threshold of the webhook is satisfied on this comparison
    """

    @property
    def name(self):
        return self.__class__.__name__

    def is_enabled(self):
        if not bool(self.site_settings):
            log.info(
                "Not notifying on %s, because it is not enabled on site-level settings",
                self.name
            )
            return False
        if not self.notifier_yaml_settings.get('url'):
            log.warning(
                "Not notifying because webhook had no url"
            )
            return False
        parsed_url = urlparse(self.notifier_yaml_settings.get('url'))
        if isinstance(self.site_settings, list) and parsed_url.netloc not in self.site_settings:
            log.warning(
                "Not notifying because url not permitted by site settings"
            )
            return False
        return True

    def should_notify_comparison(self, comparison):
        head_full_commit = comparison.head
        if not match(self.notifier_yaml_settings.get('branches'), head_full_commit.commit.branch):
            log.warning(
                "Not notifying because branch not in expected branches",
                extra=dict(
                    commit=head_full_commit.commit.commitid,
                    repoid=head_full_commit.commit.repoid,
                    current_branch=head_full_commit.commit.branch,
                    branch_patterns=self.notifier_yaml_settings.get('branches')
                )
            )
            return False
        if not self.is_above_threshold(comparison):
            return False
        return True

    def notify(self, comparison: Comparison, **extra_data):
        head_full_commit = comparison.head
        base_full_commit = comparison.base
        with metrics.timer(f'new-worker.services.notify.{self.name}.run'):
            log.info(
                "Starting notification on %s",
                self.name,
                extra=dict(
                    repoid=head_full_commit.commit.repoid,
                    commit=head_full_commit.commit.commitid
                )
            )
            _filters = self.get_notifier_filters()
            with head_full_commit.report.filter(**_filters):
                with (base_full_commit.report.filter(**_filters) if (base_full_commit.report is not None) else WithNone()):
                    if self.should_notify_comparison(comparison):
                        result = self.do_notify(comparison, **extra_data)
            log.info(
                "Finishing notification on %s. Result was %s",
                self.name,
                'success' if result.get('successful') else 'failure',
                extra=dict(
                    result=result,
                    repoid=head_full_commit.commit.repoid,
                    commit=head_full_commit.commit.commitid
                )
            )
            return result

    def get_notifier_filters(self):
        return dict(
            paths=set(
                get_paths_from_flags(self.current_yaml, self.notifier_yaml_settings.get('flags')) +
                (self.notifier_yaml_settings.get('paths') or [])
            ),
            flags=self.notifier_yaml_settings.get('flags')
        )

    def do_notify(self, comparison):
        data = self.build_payload(comparison)
        return self.send_actual_notification(comparison, data)

    def is_above_threshold(self, comparison: Comparison):
        head_full_commit = comparison.head
        base_full_commit = comparison.base
        threshold = self.notifier_yaml_settings.get('threshold')
        if threshold is None:
            return True
        if base_full_commit.report is None:
            log.info(
                "Cannot compare commits because base commit does not have a report",
                extra=dict(
                    commit=head_full_commit.commit.commitid,
                    base_commit=base_full_commit.commit.commitid,
                )
            )
            return False
        diff_coverage = Decimal(head_full_commit.report.totals.coverage) - Decimal(base_full_commit.report.totals.coverage)
        rounded_coverage = round_number(self.current_yaml, diff_coverage)
        return rounded_coverage >= threshold

    def generate_compare_dict(self, comparison: Comparison):
        head_full_commit = comparison.head
        base_full_commit = comparison.base
        if base_full_commit.report is not None:
            difference = Decimal(head_full_commit.report.totals.coverage) - Decimal(base_full_commit.report.totals.coverage)
            message = 'no change' if difference == 0 else 'increased' if difference > 0 else 'decreased'
            notation = '' if difference == 0 else '+' if difference > 0 else '-'
        else:
            difference = None
            message = 'unknown'
            notation = ''
        return {
            "url": get_compare_url(base_full_commit.commit, head_full_commit.commit),
            "message": message,
            "coverage": round_number(self.current_yaml, difference) if difference is not None else None,
            "notation": notation
        }

    def generate_message(self, comparison: Comparison):
        if self.notifier_yaml_settings.get('message'):
            return self.notifier_yaml_settings.get('message')
        commit = comparison.head.commit
        comparison_string = ""
        if comparison.base.report is not None:
            compare = self.generate_compare_dict(comparison)
            comparison_string = self.COMPARISON_STRING.format(
                compare_message=compare['message'],
                compare_url=compare['url'],
                compare_notation=compare['notation'],
                compare_coverage=compare['coverage']
            )
        return self.BASE_MESSAGE.format(
            head_url=get_commit_url(commit),
            owner_username=commit.repository.owner.username,
            repo_name=commit.repository.name,
            comparison_string=comparison_string,
            head_branch=commit.branch,
            head_totals_c=comparison.head.report.totals.coverage,
            head_short_commitid=commit.commitid[:7]
        )


class RequestsYamlBasedNotifier(StandardNotifier):
    """
        This class is a small implementation detail for using `requests` package to communicate with
            the server we want to notify
    """

    json_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'Codecov'
    }

    def send_actual_notification(self, data: Mapping[str, Any]):
        kwargs = dict(timeout=30, headers=self.json_headers)
        res = requests.post(url=self.notifier_yaml_settings['url'], json=data, **kwargs)
        return {
            'successful': res.status_code < 400,
            'reason': None if res.status_code else res.message
        }
