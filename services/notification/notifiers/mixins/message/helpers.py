import re
from decimal import Decimal
from typing import List, Sequence

from shared.reports.resources import ReportTotals
from shared.yaml.user_yaml import UserYaml

from services.comparison import ComparisonProxy
from services.comparison.changes import Change
from services.yaml import read_yaml_field
from services.yaml.reader import get_minimum_precision, round_number

zero_change_regex = re.compile("0.0+%?")


def has_project_status(yaml: UserYaml) -> bool:
    project_status_details = read_yaml_field(
        yaml, ("coverage", "status", "project"), False
    )
    if isinstance(project_status_details, bool):
        return project_status_details
    # If it's not a bool, it has to be a dict
    if isinstance(project_status_details, dict):
        if "enabled" in project_status_details:
            return project_status_details["enabled"]
        return True
    # The config is not according to what we expect
    # So it's an invalid status definition
    return False


def is_coverage_drop_significant(comparison: ComparisonProxy) -> bool:
    head_coverage = (
        comparison.head.report.totals.coverage if comparison.has_head_report() else None
    )
    base_coverage = (
        comparison.project_coverage_base.report.totals.coverage
        if comparison.has_project_coverage_base_report()
        else None
    )
    if head_coverage is None or base_coverage is None:
        # No change to be significant
        return False
    diff = Decimal(head_coverage) - Decimal(base_coverage)
    change_is_positive = diff >= 0
    # head_coverage is the percent of the project covered in HEAD
    # base_coverage is the percent of the project covered in BASE
    # So "change_is_significant" is checking if the diff between them is more than 5%
    change_is_significant = abs(diff) >= Decimal(5)
    return not change_is_positive and change_is_significant


def make_metrics(before, after, relative, show_complexity, yaml, pull_url=None):
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
        if isinstance(before, list):
            before = ReportTotals(*before)
        if isinstance(after, list):
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
                yaml, after.coverage, style="{0}%", if_null="\u2205"
            ),
            relative=format_number_to_str(
                yaml, relative.coverage if relative else 0, style="{0}%", if_null="\xf8"
            ),
            impact=(
                format_number_to_str(
                    yaml,
                    coverage_change,
                    style="{0}%",
                    if_zero="\xf8",
                    if_null="\u2205",
                    plus=True,
                )
                if before
                else "?"
                if before is None
                else "\xf8"
            ),
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
                        yaml, relative.complexity if relative else 0, if_null="\xf8"
                    )
                ),
                impact=style.format(
                    format_number_to_str(
                        yaml,
                        complexity_change,
                        if_zero="\xf8",
                        if_null="\xf8",
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
                else (
                    " :arrow_down: |"
                    if coverage_good is False and coverage_change != 0
                    else " |"
                )
            )

    return "".join(("|", coverage, complexity, icon))


def make_patch_only_metrics(before, after, relative, show_complexity, yaml, pull_url):
    if after is None:
        # e.g. missing flags
        coverage = " `?` |"
        missing_line_str = " `?` |"

    elif after is False:
        # e.g. file deleted
        coverage = " |"
        missing_line_str = " |"

    else:
        patch_cov = format_number_to_str(
            yaml, relative.coverage if relative else 0, style="{0}%", if_null="\xf8"
        )
        coverage = f" {patch_cov} |"
        missing_lines = relative.misses if relative else 0
        partials = relative.partials if relative else 0
        s = "s" if partials > 1 else ""
        partials_str = "{n} partial{s}".format(
            n=partials,
            s=s,
        )
        missing_line_str = (
            " [{m} Missing {partials}:warning: ]({pull_url}?src=pr&el=tree) |".format(
                m=missing_lines,
                partials=f"and {partials_str} " if partials else "",
                pull_url=pull_url,
            )
        )
    return "".join(("|", coverage, missing_line_str))


def get_table_header(show_complexity):
    return (
        "| Coverage \u0394 |"
        + (" Complexity \u0394 |" if show_complexity else "")
        + " |"
    )


def get_table_layout(show_complexity):
    return "|---|---|---|" + ("---|" if show_complexity else "")


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
        text="Coverage Diff",
        fill=" ",
        align="^",
        width=row_w - 4,
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
