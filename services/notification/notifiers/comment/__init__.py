from base64 import b64encode
from itertools import starmap
from decimal import Decimal
from collections import namedtuple
import logging
from typing import Any, Mapping, List

from shared.reports.resources import Report, ReportTotals
from shared.helpers.yaml import walk
from shared.torngit.exceptions import (
    TorngitObjectNotFoundError,
    TorngitClientError,
    TorngitServerFailureError,
)

from database.enums import Notification
from services.notification.notifiers.base import (
    NotificationResult,
    AbstractBaseNotifier,
)
from services.notification.types import Comparison
from helpers.metrics import metrics

from services.yaml.reader import read_yaml_field, round_number
from services.notification.changes import get_changes
from services.repository import get_repo_provider_service
from services.urls import (
    get_pull_url,
    get_commit_url,
    get_pull_graph_url,
    get_org_account_url,
)
from services.notification.notifiers.comment.helpers import (
    sort_by_importance,
    format_number_to_str,
    ellipsis,
    diff_to_string,
    escape_markdown,
)

log = logging.getLogger(__name__)

null = namedtuple("_", ["totals"])(None)


class CommentNotifier(AbstractBaseNotifier):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._repository_service = None

    @property
    def repository_service(self):
        if not self._repository_service:
            self._repository_service = get_repo_provider_service(self.repository)
        return self._repository_service

    def store_results(self, comparison: Comparison, result: NotificationResult):
        pull = comparison.pull
        if not result.notification_attempted or not result.notification_successful:
            return
        data_received = result.data_received
        if data_received and data_received.get("id"):
            pull.commentid = data_received.get("id")

    @property
    def name(self) -> str:
        return "comment"

    @property
    def notification_type(self) -> Notification:
        return Notification.comment

    async def get_diff(self, comparison: Comparison):
        repository_service = self.repository_service
        head = comparison.head.commit
        base = comparison.base.commit
        if base is None:
            return None
        pull_diff = await repository_service.get_compare(
            base.commitid, head.commitid, with_commits=False
        )
        return pull_diff["diff"]

    async def notify(self, comparison: Comparison, **extra_data) -> NotificationResult:
        if comparison.pull is None:
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="no_pull_request",
                data_sent=None,
                data_received=None,
            )
        if (
            comparison.enriched_pull is None
            or comparison.enriched_pull.provider_pull is None
        ):
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_not_in_provider",
                data_sent=None,
                data_received=None,
            )
        if comparison.pull.state != "open":
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_closed",
                data_sent=None,
                data_received=None,
            )
        if self.notifier_yaml_settings.get("after_n_builds") is not None:
            n_builds_present = len(comparison.head.report.sessions)
            if n_builds_present < self.notifier_yaml_settings.get("after_n_builds"):
                return NotificationResult(
                    notification_attempted=False,
                    notification_successful=None,
                    explanation="not_enough_builds",
                    data_sent=None,
                    data_received=None,
                )
        try:
            with metrics.timer(
                "worker.services.notifications.notifiers.comment.build_message"
            ):
                message = await self.build_message(comparison)
        except TorngitClientError:
            log.warning(
                "Unable to fetch enough information to build message for comment",
                extra=dict(
                    commit=comparison.head.commit.commitid,
                    pullid=comparison.pull.pullid,
                ),
                exc_info=True,
            )
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="unable_build_message",
                data_sent=None,
                data_received=None,
            )
        pull = comparison.pull
        data = {"message": message, "commentid": pull.commentid, "pullid": pull.pullid}
        try:
            with metrics.timer(
                "worker.services.notifications.notifiers.comment.send_notifications"
            ):
                return await self.send_actual_notification(data)
        except TorngitServerFailureError:
            log.warning(
                "Unable to send comments because the provider server was not reachable or errored",
                extra=dict(service=self.repository.service,),
                exc_info=True,
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="provider_issue",
                data_sent=data,
                data_received=None,
            )

    async def send_actual_notification(self, data: Mapping[str, Any]):
        message = "\n".join(data["message"])
        behavior = self.notifier_yaml_settings.get("behavior", "default")
        if behavior == "default":
            res = await self.send_comment_default_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "once":
            res = await self.send_comment_once_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "new":
            res = await self.send_comment_new_behavior(
                data["pullid"], data["commentid"], message
            )
        elif behavior == "spammy":
            res = await self.send_comment_spammy_behavior(
                data["pullid"], data["commentid"], message
            )
        return NotificationResult(
            notification_attempted=res["notification_attempted"],
            notification_successful=res["notification_successful"],
            explanation=res["explanation"],
            data_sent=data,
            data_received=res["data_received"],
        )

    async def send_comment_default_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                res = await self.repository_service.edit_comment(
                    pullid, commentid, message
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": True,
                    "explanation": None,
                    "data_received": {"id": res["id"]},
                }
            except TorngitObjectNotFoundError:
                log.warning("Comment was not found to be edited")
            except TorngitClientError:
                log.warning(
                    "Comment could not be edited due to client permissions",
                    exc_info=True,
                    extra=dict(pullid=pullid, commentid=commentid),
                )
        try:
            res = await self.repository_service.post_comment(pullid, message)
            return {
                "notification_attempted": True,
                "notification_successful": True,
                "explanation": None,
                "data_received": {"id": res["id"]},
            }
        except TorngitClientError:
            log.warning(
                "Comment could not be posted due to client permissions",
                exc_info=True,
                extra=dict(pullid=pullid, commentid=commentid),
            )
            return {
                "notification_attempted": True,
                "notification_successful": False,
                "explanation": "comment_posting_permissions",
                "data_received": None,
            }

    async def send_comment_once_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                res = await self.repository_service.edit_comment(
                    pullid, commentid, message
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": True,
                    "explanation": None,
                    "data_received": {"id": res["id"]},
                }
            except TorngitObjectNotFoundError:
                log.warning("Comment was not found to be edited")
                return {
                    "notification_attempted": False,
                    "notification_successful": None,
                    "explanation": "comment_deleted",
                    "data_received": None,
                }
            except TorngitClientError:
                log.warning(
                    "Comment could not be edited due to client permissions",
                    exc_info=True,
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": False,
                    "explanation": "no_permissions",
                    "data_received": None,
                }
        res = await self.repository_service.post_comment(pullid, message)
        return {
            "notification_attempted": True,
            "notification_successful": True,
            "explanation": None,
            "data_received": {"id": res["id"]},
        }

    async def send_comment_new_behavior(self, pullid, commentid, message):
        if commentid:
            try:
                await self.repository_service.delete_comment(pullid, commentid)
            except TorngitObjectNotFoundError:
                log.info("Comment was already deleted")
            except TorngitClientError:
                log.warning(
                    "Comment could not be deleted due to client permissions",
                    exc_info=True,
                )
                return {
                    "notification_attempted": True,
                    "notification_successful": False,
                    "explanation": "no_permissions",
                    "data_received": None,
                }
        try:
            res = await self.repository_service.post_comment(pullid, message)
            return {
                "notification_attempted": True,
                "notification_successful": True,
                "explanation": None,
                "data_received": {"id": res["id"]},
            }
        except TorngitClientError:
            log.warning(
                "Comment could not be posted due to client permissions",
                exc_info=True,
                extra=dict(pullid=pullid, commentid=commentid),
            )
            return {
                "notification_attempted": True,
                "notification_successful": False,
                "explanation": "comment_posting_permissions",
                "data_received": None,
            }

    async def send_comment_spammy_behavior(self, pullid, commentid, message):
        res = await self.repository_service.post_comment(pullid, message)
        return {
            "notification_attempted": True,
            "notification_successful": True,
            "explanation": None,
            "data_received": {"id": res["id"]},
        }

    def is_enabled(self) -> bool:
        return bool(self.notifier_yaml_settings) and isinstance(
            self.notifier_yaml_settings, dict
        )

    async def build_message(self, comparison: Comparison) -> List[str]:
        if self.should_use_upgrade_decoration():
            return self._create_upgrade_message(comparison)

        with metrics.timer("worker.services.notifications.notifiers.comment.get_diff"):
            diff = await self.get_diff(comparison)
        pull_dict = comparison.enriched_pull.provider_pull
        return self._create_message(comparison, diff, pull_dict)

    def _create_upgrade_message(self, comparison):
        db_pull = comparison.enriched_pull.database_pull
        links = {
            "org_account": get_org_account_url(db_pull),
        }
        author_username = comparison.enriched_pull.provider_pull["author"].get(
            "username"
        )
        return [
            f"The author of this PR, {author_username}, is not an active member of this organization on Codecov.",
            f"Please [activate this user on Codecov]({links['org_account']}/users) to display this PR comment.",
        ]

    def _create_message(self, comparison, diff, pull_dict):
        changes = get_changes(comparison.base.report, comparison.head.report, diff)
        base_report = comparison.base.report
        head_report = comparison.head.report
        pull = comparison.pull
        settings = self.notifier_yaml_settings

        yaml = self.current_yaml
        current_yaml = self.current_yaml

        links = {
            "pull": get_pull_url(pull),
            "base": get_commit_url(comparison.base.commit)
            if comparison.base.commit is not None
            else None,
        }

        # flags
        base_flags = base_report.flags if base_report else {}
        head_flags = head_report.flags if head_report else {}
        missing_flags = set(base_flags.keys()) - set(head_flags.keys())
        flags = []
        for name, flag in head_flags.items():
            flags.append(
                {
                    "name": name,
                    "before": base_flags.get(name, null).totals,
                    "after": flag.totals,
                    "diff": flag.apply_diff(diff) if walk(diff, ("files",)) else None,
                }
            )

        for flag in missing_flags:
            flags.append(
                {"name": flag, "before": base_flags[flag], "after": None, "diff": None}
            )

        # bool: show complexity
        if read_yaml_field(self.current_yaml, ("codecov", "ui", "hide_complexity")):
            show_complexity = False
        else:
            show_complexity = bool(
                (base_report.totals if base_report else ReportTotals()).complexity
                or (head_report.totals if head_report else ReportTotals()).complexity
            )

        # table layout
        table_header = (
            "| Coverage \u0394 |"
            + (" Complexity \u0394 |" if show_complexity else "")
            + " |"
        )
        table_layout = "|---|---|---|" + ("---|" if show_complexity else "")

        change = (
            Decimal(head_report.totals.coverage) - Decimal(base_report.totals.coverage)
            if base_report and head_report
            else Decimal(0)
        )
        if base_report and head_report:
            message_internal = "> Merging [#{pull}]({links[pull]}?src=pr&el=desc) into [{base}]({links[base]}&el=desc) will **{message}** coverage{coverage}.".format(
                pull=pull.pullid,
                base=pull_dict["base"]["branch"],
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

        if base_report is None:
            base_report = Report()

        if head_report:

            def make_metrics(before, after, relative):
                coverage_good = None
                icon = " |"
                if after is None:
                    # e.g. missing flags
                    coverage = " `?` |"
                    complexity = " `?` |" if show_complexity else ""

                elif after is False:
                    # e.g. file deleted
                    coverage = " |"
                    complexity = " |" if show_complexity else ""

                else:
                    if type(before) is list:
                        before = ReportTotals(*before)
                    if type(after) is list:
                        after = ReportTotals(*after)

                    layout = " `{absolute} <{relative}> ({impact})` |"

                    coverage_change = (
                        (float(after.coverage) - float(before.coverage))
                        if before
                        else None
                    )
                    coverage_good = (coverage_change > 0) if before else None
                    coverage = layout.format(
                        absolute=format_number_to_str(
                            yaml, after.coverage, style="{0}%"
                        ),
                        relative=format_number_to_str(
                            yaml,
                            relative.coverage if relative else 0,
                            style="{0}%",
                            if_null="\xF8",
                        ),
                        impact=format_number_to_str(
                            yaml,
                            coverage_change,
                            style="{0}%",
                            if_zero="\xF8",
                            if_null="\xF8",
                            plus=True,
                        )
                        if before
                        else "?"
                        if before is None
                        else "\xF8",
                    )

                    if show_complexity:
                        is_string = isinstance(
                            relative.complexity if relative else "", str
                        )
                        style = "{0}%" if is_string else "{0}"
                        complexity_change = (
                            Decimal(after.complexity) - Decimal(before.complexity)
                            if before
                            else None
                        )
                        complexity_good = (complexity_change < 0) if before else None
                        complexity = layout.format(
                            absolute=style.format(
                                format_number_to_str(yaml, after.complexity)
                            ),
                            relative=style.format(
                                format_number_to_str(
                                    yaml,
                                    relative.complexity if relative else 0,
                                    if_null="\xF8",
                                )
                            ),
                            impact=style.format(
                                format_number_to_str(
                                    yaml,
                                    complexity_change,
                                    if_zero="\xF8",
                                    if_null="\xF8",
                                    plus=True,
                                )
                                if before
                                else "?"
                            ),
                        )

                        show_up_arrow = coverage_good and complexity_good
                        show_down_arrow = (
                            coverage_good is False and coverage_change != 0
                        ) and (complexity_good is False and complexity_change != 0)
                        icon = (
                            " :arrow_up: |"
                            if show_up_arrow
                            else " :arrow_down: |"
                            if show_down_arrow
                            else " |"
                        )

                    else:
                        complexity = ""
                        icon = (
                            " :arrow_up: |"
                            if coverage_good
                            else " :arrow_down: |"
                            if coverage_good is False and coverage_change != 0
                            else " |"
                        )

                return "".join(("|", coverage, complexity, icon))

            # loop through layouts
            for layout in map(
                lambda l: l.strip(), (settings["layout"] or "").split(",")
            ):
                if layout.startswith("flag") and flags:
                    write("| Flag " + table_header)
                    write(table_layout)
                    for flag in sorted(flags, key=lambda f: f["name"]):
                        write(
                            "| #{name} {metrics}".format(
                                name=flag["name"],
                                metrics=make_metrics(
                                    flag["before"], flag["after"], flag["diff"]
                                ),
                            )
                        )

                elif layout == "diff":
                    write("```diff")
                    lines = diff_to_string(
                        current_yaml,
                        pull_dict["base"][
                            "branch"
                        ],  # important because base may be null
                        base_report.totals if base_report else None,
                        "#%s" % pull.pullid,
                        head_report.totals,
                    )
                    for l in lines:
                        write(l)
                    write("```")

                elif layout.startswith(("files", "tree")):

                    # create list of files changed in diff
                    files_in_diff = [
                        (
                            _diff["type"],
                            path,
                            make_metrics(
                                base_report.get(path, null).totals or False,
                                head_report.get(path, null).totals or False,
                                _diff["totals"],
                            ),
                            Decimal(_diff["totals"].coverage)
                            if _diff["totals"].coverage is not None
                            else None,
                        )
                        for path, _diff in (diff["files"] if diff else {}).items()
                        if _diff.get("totals")
                    ]

                    if files_in_diff or changes:
                        # add table headers
                        write(
                            "| [Impacted Files]({0}?src=pr&el=tree) {1}".format(
                                links["pull"], table_header
                            )
                        )
                        write(table_layout)

                        # get limit of results to show
                        limit = int(layout.split(":")[1] if ":" in layout else 10)
                        mentioned = []

                        def tree_cell(typ, path, metrics, _=None):
                            if path not in mentioned:
                                # mentioned: for files that are in diff and changes
                                mentioned.append(path)
                                return "| {rm}[{path}]({compare}/diff?src=pr&el=tree#diff-{hash}){rm} {metrics}".format(
                                    rm="~~" if typ == "deleted" else "",
                                    path=escape_markdown(ellipsis(path, 50, False)),
                                    compare=links["pull"],
                                    hash=b64encode(path.encode()).decode(),
                                    metrics=metrics,
                                )

                        # add to comment
                        for line in starmap(
                            tree_cell,
                            sorted(files_in_diff, key=lambda a: a[3] or Decimal("0"))[
                                :limit
                            ],
                        ):
                            write(line)

                        # reduce limit
                        limit = limit - len(files_in_diff)

                        # append changes
                        if limit > 0 and changes:
                            most_important_changes = sort_by_importance(changes)[:limit]
                            for change in most_important_changes:
                                celled = tree_cell(
                                    "changed",
                                    change.path,
                                    make_metrics(
                                        base_report.get(change.path, null).totals
                                        or False,
                                        head_report.get(change.path, null).totals
                                        or False,
                                        None,
                                    ),
                                )
                                write(celled)

                        remaining = len(changes or []) - limit
                        if remaining > 0:
                            write(
                                "| ... and [{n} more]({href}/diff?src=pr&el=tree-more) | |".format(
                                    n=remaining, href=links["pull"]
                                )
                            )

                elif layout == "reach":
                    write(
                        "[![Impacted file tree graph]({})]({}?src=pr&el=tree)".format(
                            get_pull_graph_url(
                                pull,
                                "tree.svg",
                                width=650,
                                height=150,
                                src="pr",
                                token=pull.repository.image_token,
                            ),
                            links["pull"],
                        )
                    )

                elif layout == "footer":
                    write("------")
                    write("")
                    write(
                        "[Continue to review full report at Codecov]({0}?src=pr&el=continue).".format(
                            links["pull"]
                        )
                    )
                    write(
                        "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)"
                    )
                    write(
                        "> `\u0394 = absolute <relative> (impact)`, `\xF8 = not affected`, `? = missing data`"
                    )
                    write(
                        "> Powered by [Codecov]({pull}?src=pr&el=footer). Last update [{base}...{head}]({pull}?src=pr&el=lastupdated). Read the [comment docs]({comment}).".format(
                            pull=links["pull"],
                            base=pull_dict["base"]["commitid"][:7],
                            head=pull_dict["head"]["commitid"][:7],
                            comment="https://docs.codecov.io/docs/pull-request-comments",
                        )
                    )

                write("")  # nl at end of each layout

        return [m for m in message if m is not None]
