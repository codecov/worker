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

        change = (
            Decimal(head_report.totals.coverage) - Decimal(base_report.totals.coverage)
            if base_report and head_report
            else Decimal(0)
        )
        if base_report and head_report:
            message_internal = "> Merging [#{pull}]({links[pull]}?src=pr&el=desc) ({commitid_head}) into [{base}]({links[base]}?el=desc) ({commitid_base}) will **{message}** coverage{coverage}.".format(
                pull=pull.pullid,
                base=pull_dict["base"]["branch"],
                commitid_head=comparison.head.commit.commitid[:7],
                commitid_base=comparison.base.commit.commitid[:7],
                # ternary operator, see https://stackoverflow.com/questions/394809/does-python-have-a-ternary-conditional-operator
                message={False: "decrease", "na": "not change", True: "increase"}[
                    (change > 0) if change != 0 else "na"
                ],
                coverage={
                    True: " by `{0}%`".format(round_number(yaml, abs(change))),
                    False: "",
                }[(change != 0)],
                links=links,
            )
        else:
            message_internal = "> :exclamation: No coverage uploaded for pull request {what} (`{branch}@{commit}`). [Click here to learn what that means](https://docs.codecov.io/docs/error-reference#section-missing-{what}-commit).".format(
                what="base" if not base_report else "head",
                branch=pull_dict["base" if not base_report else "head"]["branch"],
                commit=pull_dict["base" if not base_report else "head"]["commitid"][:7],
            )
        diff_totals = head_report.apply_diff(diff)
        message = [
            f'# [Codecov]({links["pull"]}?src=pr&el=h1) Report',
            message_internal,
            (
                "> The diff coverage is `{0}%`.".format(
                    round_number(yaml, Decimal(diff_totals.coverage))
                )
                if diff_totals and diff_totals.coverage is not None
                else "> The diff coverage is `n/a`."
            ),
            "",
        ]
        write = message.append
        # note: since we're using append, calling write("") will add a newline to the message

        if base_report is None:
            base_report = Report()

        is_compact_message = should_message_be_compact(comparison, settings)

        if (
            comparison.enriched_pull.provider_pull is not None
            and comparison.head.commit.commitid
            != comparison.enriched_pull.provider_pull["head"]["commitid"]
        ):
            # Temporary log so we understand when this happens
            log.info(
                "Notifying user that current head and pull head differ",
                extra=dict(
                    repoid=comparison.head.commit.repoid,
                    commit=comparison.head.commit.commitid,
                    pull_head=comparison.enriched_pull.provider_pull["head"][
                        "commitid"
                    ],
                ),
            )
            write(
                "> :exclamation: Current head {current_head} differs from pull request most recent head {pull_head}. Consider uploading reports for the commit {pull_head} to get more accurate results".format(
                    pull_head=comparison.enriched_pull.provider_pull["head"][
                        "commitid"
                    ][:7],
                    current_head=comparison.head.commit.commitid[:7],
                )
            )
            write("")
        if settings.get("show_critical_paths"):
            all_potentially_affected_critical_files = set(
                (diff["files"] if diff else {}).keys()
            ) | set(c.path for c in changes or [])
            overlay = comparison.get_overlay(OverlayType.line_execution_count)
            files_in_critical = set(
                overlay.search_files_for_critical_changes(
                    all_potentially_affected_critical_files
                )
            )
            if files_in_critical:
                write(
                    "Changes have been made to critical files, which contain lines commonly executed in production"
                )
                write("")
        if is_compact_message:
            write("<details><summary>Details</summary>\n")

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

        if is_compact_message:
            write("</details>")

        return [m for m in message if m is not None]

    def get_layout_section_names(self, settings):
        return map(lambda l: l.strip(), (settings["layout"] or "").split(","))
