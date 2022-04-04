import logging
from decimal import Decimal

from shared.reports.resources import Report, ReportTotals
from shared.validation.helpers import LayoutStructure

from helpers.metrics import metrics
from services.comparison import ComparisonProxy
from services.comparison.overlays import OverlayType
from services.notification.notifiers.mixins.message.helpers import (
    should_message_be_compact,
)
from services.notification.notifiers.mixins.message.sections import (
    NullSectionWriter,
    get_section_class_from_layout_name,
)
from services.urls import get_commit_url, get_pull_url
from services.yaml.reader import read_yaml_field, round_number

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
        diff = await comparison.get_diff()
        base_report = comparison.base.report
        head_report = comparison.head.report
        pull = comparison.pull

        settings = yaml_settings

        yaml = self.current_yaml
        current_yaml = self.current_yaml

        links = {
            "pull": get_pull_url(pull),
            "base": get_commit_url(comparison.base.commit)
            if comparison.base.commit is not None
            else None,
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
            f'# [Codecov]({links["pull"]}?src=pr&el=h1) Report',
        ]

        write = message.append
        # note: since we're using append, calling write("") will add a newline to the message

        if base_report is None:
            base_report = Report()

        is_compact_message = should_message_be_compact(comparison, settings)

        self.add_header_to_settings(settings)

        if head_report:
            # loop through layouts
            for layout in self.get_layout_section_names(settings):
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
                with metrics.timer(
                    f"worker.services.notifications.notifiers.comment.section.{section_writer.name}"
                ):
                    for line in await section_writer.write_section(
                        comparison, diff, changes, links
                    ):
                        write(line)

                write("")  # nl at end of each layout

        if is_compact_message and not self.should_serve_new_layout():
            write("</details> ")

        return [m for m in message if m is not None]

    def get_layout_section_names(self, settings):
        return map(lambda l: l.strip(), (settings["layout"] or "").split(","))

    def should_serve_new_layout(self):
        return False

    def add_header_to_settings(self, settings):
        if self.should_serve_new_layout():
            settings["layout"] = "newheader," + settings["layout"]
        else:
            settings["layout"] = "header," + settings["layout"]
