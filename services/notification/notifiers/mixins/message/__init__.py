import logging
from typing import Callable, List

from shared.django_apps.core.models import Repository
from shared.reports.resources import ReportTotals
from shared.validation.helpers import LayoutStructure

from database.models.core import Owner
from helpers.environment import is_enterprise
from helpers.metrics import metrics
from services.billing import BillingPlan
from services.comparison import ComparisonProxy, FilteredComparison
from services.notification.notifiers.mixins.message.helpers import (
    should_message_be_compact,
)
from services.notification.notifiers.mixins.message.sections import (
    NullSectionWriter,
    get_section_class_from_layout_name,
)
from services.notification.notifiers.mixins.message.writers import TeamPlanWriter
from services.urls import get_commit_url, get_pull_url
from services.yaml.reader import read_yaml_field

log = logging.getLogger(__name__)


class MessageMixin(object):
    def create_message(
        self, comparison: ComparisonProxy | FilteredComparison, pull_dict, yaml_settings
    ):
        """
        Assemble the various components of the PR comments message in accordance with their YAML configuration.
        See https://docs.codecov.io/docs/pull-request-comments for more context on the different parts of a PR comment.

        Returns the PR comment message as a list of strings, where each item in the list corresponds to a line in the comment.

        Parameters:
            yaml_settings: YAML settings for notifier

                Note: Github Checks Notifers are initialized with "status" YAML settings.
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
        if read_yaml_field(self.current_yaml, ("codecov", "ui", "hide_complexity")):
            show_complexity = False
        else:
            show_complexity = bool(
                (base_report.totals if base_report else ReportTotals()).complexity
                or (head_report.totals if head_report else ReportTotals()).complexity
            )

        message = []
        # note: since we're using append, calling write("") will add a newline to the message
        write = message.append

        self._possibly_write_install_app(comparison, write)

        # Write Header
        write(f'## [Codecov]({links["pull"]}?dropdown=coverage&src=pr&el=h1) Report')

        repo = comparison.head.commit.repository
        owner: Owner = repo.owner

        # Separate PR comment based on plan that can't/won't be tweaked by codecov.yml settings
        if (
            owner.plan == BillingPlan.team_monthly.value
            or owner.plan == BillingPlan.team_yearly.value
        ):
            return self._team_plan_notification(
                comparison=comparison,
                message=message,
                diff=diff,
                settings=settings,
                links=links,
                current_yaml=current_yaml,
            )

        upper_section_names = self.get_upper_section_names(settings)
        # We write the header and then the messages_to_user section
        upper_section_names.append("messages_to_user")
        for upper_section_name in upper_section_names:
            section_writer_class = get_section_class_from_layout_name(
                upper_section_name
            )
            section_writer = section_writer_class(
                self.repository,
                upper_section_name,
                show_complexity,
                settings,
                current_yaml,
            )

            self.write_section_to_msg(
                comparison, changes, diff, links, write, section_writer, behind_by
            )

        is_compact_message = should_message_be_compact(comparison, settings)

        if head_report:
            if is_compact_message:
                write(
                    "<details><summary>Additional details and impacted files</summary>\n"
                )
                write("")

            for layout in self.get_middle_layout_section_names(settings):
                section_writer_class = get_section_class_from_layout_name(layout)
                if section_writer_class is not None:
                    section_writer = section_writer_class(
                        self.repository, layout, show_complexity, settings, current_yaml
                    )
                else:
                    if layout not in LayoutStructure.acceptable_objects:
                        log.warning(
                            "Improper layout name",
                            extra=dict(
                                repoid=comparison.head.commit.repoid,
                                layout_name=layout,
                                commit=comparison.head.commit.commitid,
                            ),
                        )
                    section_writer = NullSectionWriter(
                        self.repository, layout, show_complexity, settings, current_yaml
                    )

                self.write_section_to_msg(
                    comparison,
                    changes,
                    diff,
                    links,
                    write,
                    section_writer,
                )

            if is_compact_message:
                write("</details>")

            lower_section_name = self.get_lower_section_name(settings)
            if lower_section_name is not None:
                section_writer_class = get_section_class_from_layout_name(
                    lower_section_name
                )
                if section_writer_class is not None:
                    section_writer = section_writer_class(
                        self.repository,
                        lower_section_name,
                        show_complexity,
                        settings,
                        current_yaml,
                    )
                    self.write_section_to_msg(
                        comparison,
                        changes,
                        diff,
                        links,
                        write,
                        section_writer,
                    )

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
        message: List[str],
        diff,
        settings,
        links,
        current_yaml,
    ) -> List[str]:
        writer_class = TeamPlanWriter()

        with metrics.timer(
            f"worker.services.notifications.notifiers.comment.section.{writer_class.name}"
        ):
            # Settings here enable failed tests results for now as a new product
            message.extend(
                line
                for line in writer_class.header_lines(
                    comparison=comparison, diff=diff, settings=settings
                )
            )
            message.extend(
                line
                for line in writer_class.middle_lines(
                    comparison=comparison,
                    diff=diff,
                    links=links,
                    current_yaml=current_yaml,
                )
            )
            message.extend(line for line in writer_class.footer_lines())

            return message

    def write_section_to_msg(
        self, comparison, changes, diff, links, write, section_writer, behind_by=None
    ):
        wrote_something: bool = False
        with metrics.timer(
            f"worker.services.notifications.notifiers.comment.section.{section_writer.name}"
        ):
            for line in section_writer.write_section(
                comparison, diff, changes, links, behind_by=behind_by
            ):
                wrote_something |= line is not None
                write(line)
        if wrote_something:
            write("")

    def get_middle_layout_section_names(self, settings):
        sections = map(
            lambda layout: layout.strip(), (settings["layout"] or "").split(",")
        )
        return [
            section
            for section in sections
            if section
            not in [
                "header",
                "newheader",
                "newfooter",
                "newfiles",
                "condensed_header",
                "condensed_footer",
                "condensed_files",
            ]
        ]

    def get_upper_section_names(self, settings):
        sections = list(
            map(lambda layout: layout.strip(), (settings["layout"] or "").split(","))
        )
        headers = ["newheader", "header", "condensed_header"]
        if all(x not in sections for x in headers):
            sections.insert(0, "condensed_header")

        if "files" in sections or "tree" in sections:
            sections.append("newfiles")

        return [
            section
            for section in sections
            if section
            in [
                "header",
                "newheader",
                "condensed_header",
                "newfiles",
                "condensed_files",
            ]
        ]

    def get_lower_section_name(self, settings):
        if (
            "newfooter" in settings["layout"]
            or "condensed_footer" in settings["layout"]
        ):
            return "newfooter"
