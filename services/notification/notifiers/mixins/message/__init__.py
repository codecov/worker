import logging
from typing import Any, Callable, Mapping, Optional

from shared.django_apps.core.models import Repository
from shared.plan.constants import TierName
from shared.plan.service import PlanService
from shared.reports.resources import ReportTotals

from database.models.core import Owner
from helpers.environment import is_enterprise
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.mixins.message.helpers import (
    should_message_be_compact,
)
from services.notification.notifiers.mixins.message.sections import get_message_layout
from services.notification.notifiers.mixins.message.writers import TeamPlanWriter
from services.urls import get_commit_url, get_pull_url
from services.yaml.reader import read_yaml_field

log = logging.getLogger(__name__)


class MessageMixin(object):
    def create_message(
        self,
        comparison: ComparisonProxy | FilteredComparison,
        pull_dict: Optional[Mapping[str, Any]],
        yaml_settings: dict,
        status_or_checks_helper_text: Optional[dict[str, str]] = None,
    ):
        """
        Assemble the various components of the PR comments message in accordance with their YAML configuration.
        See https://docs.codecov.io/docs/pull-request-comments for more context on the different parts of a PR comment.

        Returns the PR comment message as a list of strings, where each item in the list corresponds to a line in the comment.

        Parameters:
            yaml_settings: YAML settings for notifier

                Note: Github Checks Notifiers are initialized with "status" YAML settings.
                      Thus, the comment block of the codecov YAML is passed as the "yaml_settings" parameter for these Notifiers.

        """
        changes = comparison.get_changes()
        diff = comparison.get_diff(use_original_base=True)
        behind_by = comparison.get_behind_by()
        base_report = comparison.project_coverage_base.report
        head_report = comparison.head.report
        pull = comparison.pull

        settings = yaml_settings
        current_yaml = self.current_yaml

        links = {
            "pull": get_pull_url(pull),
            "base": (
                get_commit_url(comparison.project_coverage_base.commit)
                if comparison.project_coverage_base.commit is not None
                else None
            ),
            "head": get_commit_url(comparison.head.commit),
        }

        # bool: show complexity
        if read_yaml_field(current_yaml, ("codecov", "ui", "hide_complexity")):
            show_complexity = False
        else:
            show_complexity = bool(
                (base_report.totals if base_report else ReportTotals()).complexity
                or (head_report.totals if head_report else ReportTotals()).complexity
            )

        message: list[str] = []
        # note: since we're using append, calling write("") will add a newline to the message
        write = message.append

        self._possibly_write_install_app(comparison, write)

        # Write Header
        write(f"## [Codecov]({links['pull']}?dropdown=coverage&src=pr&el=h1) Report")

        repo = comparison.head.commit.repository
        owner: Owner = repo.owner

        # Separate PR comment based on plan that can't/won't be tweaked by codecov.yml settings
        owner_plan = PlanService(owner)
        if owner_plan.tier_name == TierName.TEAM.value:
            return self._team_plan_notification(
                comparison=comparison,
                message=message,
                diff=diff,
                settings=settings,
                links=links,
                current_yaml=current_yaml,
            )

        sections = get_message_layout(settings, status_or_checks_helper_text)

        for upper_section_name, section_writer_class in sections.upper:
            section_writer = section_writer_class(
                self.repository,
                upper_section_name,
                show_complexity,
                settings,
                current_yaml,
                status_or_checks_helper_text,
            )
            self.write_section_to_msg(
                comparison, changes, diff, links, write, section_writer, behind_by
            )

        if head_report:
            is_compact_message = sections.middle and should_message_be_compact(
                comparison, settings
            )
            if is_compact_message:
                write(
                    "<details><summary>Additional details and impacted files</summary>\n"
                )
                write("")

            for layout, section_writer_class in sections.middle:
                section_writer = section_writer_class(
                    self.repository, layout, show_complexity, settings, current_yaml
                )
                self.write_section_to_msg(
                    comparison, changes, diff, links, write, section_writer
                )

            if is_compact_message:
                write("</details>")

            for lower_section_name, section_writer_class in sections.lower:
                section_writer = section_writer_class(
                    self.repository,
                    lower_section_name,
                    show_complexity,
                    settings,
                    current_yaml,
                )
                self.write_section_to_msg(
                    comparison, changes, diff, links, write, section_writer
                )

        # TODO(swatinem): should this rather be part of the `announcements` section
        self.write_cross_pollination_message(write=write)

        return [m for m in message if m is not None]

    def _possibly_write_install_app(
        self, comparison: ComparisonProxy, write: Callable
    ) -> None:
        """Write a message if the user does not have any GH installations
        and will be writing with a Codecov Commenter Account.
        """
        repo: Repository = comparison.head.commit.repository
        repo_owner: Owner = repo.owner
        if (
            repo_owner.service == "github"
            and not is_enterprise()
            and repo_owner.github_app_installations == []
            and comparison.context.gh_is_using_codecov_commenter
        ):
            message_to_display = ":warning: Please install the !['codecov app svg image'](https://github.com/codecov/engineering-team/assets/152432831/e90313f4-9d3a-4b63-8b54-cfe14e7ec20d) to ensure uploads and comments are reliably processed by Codecov."
            write(message_to_display)
            write("")

    def _team_plan_notification(
        self,
        comparison: ComparisonProxy,
        message: list[str],
        diff,
        settings,
        links,
        current_yaml,
    ) -> list[str]:
        writer_class = TeamPlanWriter()

        # Settings here enable failed tests results for now as a new product
        message.extend(
            writer_class.header_lines(
                comparison=comparison, diff=diff, settings=settings
            )
        )
        message.extend(
            writer_class.middle_lines(
                comparison=comparison, diff=diff, links=links, current_yaml=current_yaml
            )
        )
        message.extend(writer_class.footer_lines(comparison))

        return message

    def write_section_to_msg(
        self, comparison, changes, diff, links, write, section_writer, behind_by=None
    ):
        wrote_something = False
        for line in section_writer.write_section(
            comparison, diff, changes, links, behind_by=behind_by
        ):
            wrote_something |= line is not None
            write(line)
        if wrote_something:
            write("")

    def write_cross_pollination_message(self, write: Callable):
        extra_message = []

        ta_message = "- :snowflake: [Test Analytics](https://docs.codecov.com/docs/test-analytics): Detect flaky tests, report on failures, and find test suite problems."
        ba_message = "- :package: [JS Bundle Analysis](https://docs.codecov.com/docs/javascript-bundle-analysis): Save yourself from yourself by tracking and limiting bundle sizes in JS merges."

        if not self.repository.test_analytics_enabled:
            extra_message.append(ta_message)

        if not self.repository.bundle_analysis_enabled and set(
            {"javascript", "typescript"}
        ).intersection(self.repository.languages or {}):
            extra_message.append(ba_message)

        if extra_message:
            for i in [
                "<details><summary> :rocket: New features to boost your workflow: </summary>",
                "",
                *extra_message,
                "</details>",
            ]:
                write(i)
