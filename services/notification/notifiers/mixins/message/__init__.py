import logging
from typing import List

from shared.reports.resources import Report, ReportTotals
from shared.validation.helpers import LayoutStructure

from database.models.core import Owner
from helpers.metrics import metrics
from services.billing import BillingPlan
from services.comparison import ComparisonProxy
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
    async def create_message(
        self, comparison: ComparisonProxy, pull_dict, yaml_settings
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
        changes = await comparison.get_changes()
        diff = await comparison.get_diff(use_original_base=True)
        behind_by = await comparison.get_behind_by()
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

        message = [
            f'## [Codecov]({links["pull"]}?dropdown=coverage&src=pr&el=h1) Report',
        ]

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

        write = message.append
        # note: since we're using append, calling write("") will add a newline to the message

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

            await self.write_section_to_msg(
                comparison, changes, diff, links, write, section_writer, behind_by
            )

        is_compact_message = should_message_be_compact(comparison, settings)

        if base_report is None:
            base_report = Report()

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

                await self.write_section_to_msg(
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
                    await self.write_section_to_msg(
                        comparison,
                        changes,
                        diff,
                        links,
                        write,
                        section_writer,
                    )

        return [m for m in message if m is not None]

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
            for line in writer_class.header_lines(
                comparison=comparison, diff=diff, settings=settings
            ):
                message.append(line)
            for line in writer_class.middle_lines(
                comparison=comparison,
                diff=diff,
                links=links,
                current_yaml=current_yaml,
            ):
                message.append(line)
            for line in writer_class.footer_lines():
                message.append(line)

            return message

    async def write_section_to_msg(
        self, comparison, changes, diff, links, write, section_writer, behind_by=None
    ):
        wrote_something: bool = False
        with metrics.timer(
            f"worker.services.notifications.notifiers.comment.section.{section_writer.name}"
        ):
            for line in await section_writer.write_section(
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
