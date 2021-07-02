import re
import logging
from decimal import Decimal
from typing import Sequence, List
from itertools import starmap
from base64 import b64encode
from collections import namedtuple

from services.urls import (
    get_pull_url,
    get_commit_url,
    get_pull_graph_url,
    get_commit_url_from_commit_sha,
)
from services.yaml.reader import read_yaml_field, round_number, get_minimum_precision
from shared.helpers.yaml import walk
from shared.reports.resources import Report, ReportTotals
from shared.validation.helpers import LayoutStructure
from services.comparison.changes import Change
from helpers.metrics import metrics
from services.comparison import ComparisonProxy

log = logging.getLogger(__name__)

null = namedtuple("_", ["totals"])(None)
zero_change_regex = re.compile("0.0+%?")


def make_metrics(before, after, relative, show_complexity, yaml):
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

        if (
            before
            and before.coverage is not None
            and after
            and after.coverage is not None
        ):
            coverage_change = float(after.coverage) - float(before.coverage)
        else:
            coverage_change = None
        coverage_good = (coverage_change > 0) if coverage_change is not None else None
        coverage = layout.format(
            absolute=format_number_to_str(
                yaml, after.coverage, style="{0}%", if_null="\u2205",
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
                if_null="\u2205",
                plus=True,
            )
            if before
            else "?"
            if before is None
            else "\xF8",
        )

        if show_complexity:
            is_string = isinstance(relative.complexity if relative else "", str)
            style = "{0}%" if is_string else "{0}"
            complexity_change = (
                Decimal(after.complexity) - Decimal(before.complexity)
                if before
                else None
            )
            complexity_good = (complexity_change < 0) if before else None
            complexity = layout.format(
                absolute=style.format(format_number_to_str(yaml, after.complexity)),
                relative=style.format(
                    format_number_to_str(
                        yaml, relative.complexity if relative else 0, if_null="\xF8",
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
            show_down_arrow = (coverage_good is False and coverage_change != 0) and (
                complexity_good is False and complexity_change != 0
            )
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

        if is_compact_message:
            write("<details><summary>Details</summary>\n")

        if head_report:
            # loop through layouts
            for layout in map(
                lambda l: l.strip(), (settings["layout"] or "").split(",")
            ):
                if layout.startswith("flag"):
                    section_writer = FlagSectionWriter(
                        self.repository, layout, show_complexity, settings, current_yaml
                    )
                elif layout == "diff":
                    section_writer = DiffSectionWriter(
                        self.repository, layout, show_complexity, settings, current_yaml
                    )
                elif layout.startswith(("files", "tree")):
                    section_writer = FileSectionWriter(
                        self.repository, layout, show_complexity, settings, current_yaml
                    )
                elif layout == "reach":
                    section_writer = ReachSectionWriter(
                        self.repository, layout, show_complexity, settings, current_yaml
                    )
                elif layout == "footer":
                    section_writer = FooterSectionWriter(
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
                    for line in section_writer.write_section(
                        comparison, diff, changes, links
                    ):
                        write(line)
                write("")  # nl at end of each layout

        if is_compact_message:
            write("</details>")

        return [m for m in message if m is not None]


class BaseSectionWriter(object):
    def __init__(self, repository, layout, show_complexity, settings, current_yaml):
        self.repository = repository
        self.layout = layout
        self.show_complexity = show_complexity
        self.settings = settings
        self.current_yaml = current_yaml

    @property
    def name(self):
        return self.__class__.__name__


class NullSectionWriter(BaseSectionWriter):
    def write_section(*args, **kwargs):
        return []


class FooterSectionWriter(BaseSectionWriter):
    def write_section(
        self, comparison, diff, changes, links,
    ):
        pull_dict = comparison.enriched_pull.provider_pull
        yield ("------")
        yield ("")
        yield (
            "[Continue to review full report at Codecov]({0}?src=pr&el=continue).".format(
                links["pull"]
            )
        )
        yield (
            "> **Legend** - [Click here to learn more](https://docs.codecov.io/docs/codecov-delta)"
        )
        yield (
            "> `\u0394 = absolute <relative> (impact)`, `\xF8 = not affected`, `? = missing data`"
        )
        yield (
            "> Powered by [Codecov]({pull}?src=pr&el=footer). Last update [{base}...{head}]({pull}?src=pr&el=lastupdated). Read the [comment docs]({comment}).".format(
                pull=links["pull"],
                base=pull_dict["base"]["commitid"][:7],
                head=pull_dict["head"]["commitid"][:7],
                comment="https://docs.codecov.io/docs/pull-request-comments",
            )
        )


class ReachSectionWriter(BaseSectionWriter):
    def write_section(
        self, comparison, diff, changes, links,
    ):
        pull = comparison.enriched_pull.database_pull
        yield (
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


class DiffSectionWriter(BaseSectionWriter):
    def write_section(
        self, comparison, diff, changes, links,
    ):
        base_report = comparison.base.report
        head_report = comparison.head.report
        if base_report is None:
            base_report = Report()
        pull_dict = comparison.enriched_pull.provider_pull
        pull = comparison.enriched_pull.database_pull
        yield ("```diff")
        lines = diff_to_string(
            self.current_yaml,
            pull_dict["base"]["branch"],  # important because base may be null
            base_report.totals if base_report else None,
            "#%s" % pull.pullid,
            head_report.totals,
        )
        for l in lines:
            yield (l)
        yield ("```")


class FileSectionWriter(BaseSectionWriter):
    def write_section(
        self, comparison, diff, changes, links,
    ):
        # create list of files changed in diff
        base_report = comparison.base.report
        head_report = comparison.head.report
        if base_report is None:
            base_report = Report()
        files_in_diff = [
            (
                _diff["type"],
                path,
                make_metrics(
                    base_report.get(path, null).totals or False,
                    head_report.get(path, null).totals or False,
                    _diff["totals"],
                    self.show_complexity,
                    self.current_yaml,
                ),
                Decimal(_diff["totals"].coverage)
                if _diff["totals"].coverage is not None
                else None,
            )
            for path, _diff in (diff["files"] if diff else {}).items()
            if _diff.get("totals")
        ]

        if files_in_diff or changes:
            table_header = (
                "| Coverage \u0394 |"
                + (" Complexity \u0394 |" if self.show_complexity else "")
                + " |"
            )
            table_layout = "|---|---|---|" + ("---|" if self.show_complexity else "")
            # add table headers
            yield (
                "| [Impacted Files]({0}?src=pr&el=tree) {1}".format(
                    links["pull"], table_header
                )
            )
            yield (table_layout)

            # get limit of results to show
            limit = int(self.layout.split(":")[1] if ":" in self.layout else 10)
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
                sorted(files_in_diff, key=lambda a: a[3] or Decimal("0"))[:limit],
            ):
                yield (line)

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
                            base_report.get(change.path, null).totals or False,
                            head_report.get(change.path, null).totals or False,
                            None,
                            self.show_complexity,
                            self.current_yaml,
                        ),
                    )
                    yield (celled)

            remaining = len(changes or []) - limit
            if remaining > 0:
                yield (
                    "| ... and [{n} more]({href}/diff?src=pr&el=tree-more) | |".format(
                        n=remaining, href=links["pull"]
                    )
                )


class FlagSectionWriter(BaseSectionWriter):
    def write_section(
        self, comparison, diff, changes, links,
    ):
        # flags
        base_report = comparison.base.report
        head_report = comparison.head.report
        if base_report is None:
            base_report = Report()
        base_flags = base_report.flags if base_report else {}
        head_flags = head_report.flags if head_report else {}
        missing_flags = set(base_flags.keys()) - set(head_flags.keys())
        flags = []

        show_carriedforward_flags = self.settings.get("show_carryforward_flags", False)
        for name, flag in head_flags.items():
            if (show_carriedforward_flags is True) or (  # Include all flags
                show_carriedforward_flags is False
                and flag.carriedforward
                is False  # Only include flags without carriedforward coverage
            ):
                flags.append(
                    {
                        "name": name,
                        "before": base_flags.get(name, null).totals,
                        "after": flag.totals,
                        "diff": flag.apply_diff(diff)
                        if walk(diff, ("files",))
                        else None,
                        "carriedforward": flag.carriedforward,
                        "carriedforward_from": flag.carriedforward_from,
                    }
                )

        for flag in missing_flags:
            flags.append(
                {
                    "name": flag,
                    "before": base_flags[flag],
                    "after": None,
                    "diff": None,
                    "carriedforward": False,
                    "carriedforward_from": None,
                }
            )

        # TODO: get icons working
        # flag_icon_url = ""
        # carriedforward_flag_icon_url = ""

        if flags:
            # Even if "show_carryforward_flags" is true, we don't want to show that column if there isn't actually carriedforward coverage,
            # so figure out if we actually have any carriedforward coverage to show
            has_carriedforward_flags = any(
                flag["carriedforward"] is True
                for flag in flags  # If "show_carryforward_flags" yaml setting is set to false there won't be any flags in this list with carriedforward coverage.
            )

            table_header = (
                "| Coverage \u0394 |"
                + (" Complexity \u0394 |" if self.show_complexity else "")
                + " |"
                + (" *Carryforward flag |" if has_carriedforward_flags else "")
            )
            table_layout = (
                "|---|---|---|"
                + ("---|" if self.show_complexity else "")
                + ("---|" if has_carriedforward_flags else "")
            )

            yield ("| Flag " + table_header)
            yield (table_layout)
            for flag in sorted(flags, key=lambda f: f["name"]):
                carriedforward, carriedforward_from = (
                    flag["carriedforward"],
                    flag["carriedforward_from"],
                )
                # Format the message for the "carriedforward" column, if the flag was carried forward
                if carriedforward is True:
                    # The "from <link to parent commit>" text will only appear if we actually know which commit we carried forward from
                    carriedforward_from_url = (
                        get_commit_url_from_commit_sha(
                            self.repository, carriedforward_from
                        )
                        if carriedforward_from
                        else ""
                    )

                    carriedforward_message = (
                        " Carriedforward"
                        + (
                            f" from [{carriedforward_from[:7]}]({carriedforward_from_url})"
                            if carriedforward_from and carriedforward_from_url
                            else ""
                        )
                        + " |"
                    )
                else:
                    carriedforward_message = " |" if has_carriedforward_flags else ""

                yield (
                    "| {name} {metrics}{cf}".format(
                        name=flag["name"],
                        metrics=make_metrics(
                            flag["before"],
                            flag["after"],
                            flag["diff"],
                            self.show_complexity,
                            self.current_yaml,
                        ),
                        cf=carriedforward_message,
                    )
                )

            if has_carriedforward_flags and show_carriedforward_flags:
                yield ("")
                yield (
                    "*This pull request uses carry forward flags. [Click here](https://docs.codecov.io/docs/carryforward-flags) to find out more."
                )
            elif not show_carriedforward_flags:
                yield ("")
                yield (
                    "Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more."
                )


def format_number_to_str(
    yml, value, if_zero=None, if_null=None, plus=False, style="{0}"
) -> str:
    if value is None:
        return if_null
    precision = get_minimum_precision(yml)
    value = Decimal(value)
    res = round_number(yml, value)

    if if_zero and value == 0:
        return if_zero

    if res == 0 and value != 0:
        # <.01
        return style.format(
            "%s<%s"
            % ("+" if plus and value > 0 else "" if value > 0 else "-", precision)
        )

    if plus and res > Decimal("0"):
        res = "+" + str(res)
    return style.format(res)


def add_plus_sign(value: str) -> str:
    if value in ("", "0", "0%") or zero_change_regex.fullmatch(value):
        return ""
    elif value[0] != "-":
        return "+%s" % value
    else:
        return value


def list_to_text_table(rows, padding=0) -> List[str]:
    """
    Assumes align left.

    list_to_text_table(
      [
          ('|##', 'master|', 'stable|', '+/-|', '##|'),
          ('+', '1|', '2|', '+1', ''),
      ], 2) == ['##   master   stable   +/-   ##',
                '+         1        2    +1     ']

    """
    # (2, 6, 6, 3, 2)
    column_w = list(
        map(
            max,
            zip(*map(lambda row: map(lambda cell: len(cell.strip("|")), row), rows)),
        )
    )

    def _fill(a):
        w, cell = a
        return "{text:{fill}{align}{width}}".format(
            text=cell.strip("|"),
            fill=" ",
            align=(("^" if cell[:1] == "|" else ">") if cell[-1:] == "|" else "<"),
            width=w,
        )

    # now they are filled with spaces
    spacing = (" " * padding).join
    return list(map(lambda row: spacing(map(_fill, zip(column_w, row))), rows))


def diff_to_string(current_yaml, base_title, base, head_title, head) -> List[str]:
    """
    ('master', {},
     'stable', {},
     ('ui', before, after), ...})
    """

    def F(value):
        if value is None:
            return "?"
        elif isinstance(value, str):
            return "%s%%" % round_number(current_yaml, Decimal(value))
        else:
            return value

    def _row(title, c1, c2, plus="+", minus="-", neutral=" "):
        if c1 == c2 == 0:
            return ("", "", "", "", "")
        else:
            # TODO if coverage format to smallest string or precision
            if c1 is None or c2 is None:
                change = ""
            elif isinstance(c2, str) or isinstance(c1, str):
                change = F(str(float(c2) - float(c1)))
            else:
                change = str(c2 - c1)
            change_is_zero = change in ("0", "0%", "") or zero_change_regex.fullmatch(
                change
            )
            sign = neutral if change_is_zero else plus if change[0] != "-" else minus
            return (
                "%s %s" % (sign, title),
                "%s|" % F(c1),
                "%s|" % F(c2),
                "%s|" % add_plus_sign(change),
                "",
            )

    c = int(isinstance(base.complexity, str)) if base else 0
    # create a spaced table with data
    table = list_to_text_table(
        [
            ("|##", "%s|" % base_title, "%s|" % head_title, "+/-|", "##|"),
            _row("Coverage", base.coverage if base else None, head.coverage, "+", "-"),
            _row(
                "Complexity",
                base.complexity if base else None,
                head.complexity,
                "-+"[c],
                "+-"[c],
            ),
            _row("Files", base.files if base else None, head.files, " ", " "),
            _row("Lines", base.lines if base else None, head.lines, " ", " "),
            _row("Branches", base.branches if base else None, head.branches, " ", " "),
            _row("Hits", base.hits if base else None, head.hits, "+", "-"),
            _row("Misses", base.misses if base else None, head.misses, "-", "+"),
            _row("Partials", base.partials if base else None, head.partials, "-", "+"),
        ],
        3,
    )
    row_w = len(table[0])

    spacer = ["=" * row_w]

    title = "@@%s@@" % "{text:{fill}{align}{width}}".format(
        text="Coverage Diff", fill=" ", align="^", width=row_w - 4, strip=True
    )

    table = (
        [title, table[0]]
        + spacer
        + table[1:3]
        + spacer  # coverage, complexity
        + table[3:6]
        + spacer  # files, lines, branches
        + table[6:9]  # hits, misses, partials
    )

    # no complexity included
    if head.complexity in (None, 0):
        table.pop(4)

    return "\n".join(filter(lambda row: row.strip(" "), table)).strip("=").split("\n")


def sort_by_importance(changes: Sequence[Change]) -> List[Change]:
    return sorted(
        changes or [],
        key=lambda c: (float((c.totals or ReportTotals()).coverage), c.new, c.deleted),
    )


def ellipsis(text, length, cut_from="left") -> str:
    if cut_from == "right":
        return (text[:length] + "...") if len(text) > length else text
    elif cut_from is None:
        return (
            (text[: (length / 2)] + "..." + text[(length / -2) :])
            if len(text) > length
            else text
        )
    else:
        return ("..." + text[len(text) - length :]) if len(text) > length else text


def escape_markdown(value: str) -> str:
    return value.replace("`", "\\`").replace("*", "\\*").replace("_", "\\_")


def should_message_be_compact(comparison, settings):
    # bitbucket doesnt support <details/>
    supported_services = ("github", "gitlab")
    if comparison.repository_service.service not in supported_services:
        return False
    return settings.get("hide_comment_details", False)
