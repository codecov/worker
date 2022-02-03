from base64 import b64encode
from decimal import Decimal
from itertools import starmap

from shared.helpers.yaml import walk
from shared.reports.resources import Report

from helpers.reports import get_totals_from_file_in_reports
from services.comparison.overlays import OverlayType
from services.notification.notifiers.mixins.message.helpers import (
    diff_to_string,
    ellipsis,
    escape_markdown,
    make_metrics,
    sort_by_importance,
)
from services.urls import get_commit_url_from_commit_sha, get_pull_graph_url


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

    async def write_section(self, *args, **kwargs):
        return [i async for i in self.do_write_section(*args, **kwargs)]


class NullSectionWriter(BaseSectionWriter):
    async def write_section(*args, **kwargs):
        return []


class ImpactedEntrypointsSectionWriter(BaseSectionWriter):
    async def do_write_section(self, comparison, diff, changes, links):
        overlay = comparison.get_overlay(OverlayType.line_execution_count)
        impacted_endpoints = await overlay.find_impacted_endpoints()
        if impacted_endpoints:
            yield "| Related Entrypoints |"
            yield "|---|"
            for endpoint in impacted_endpoints:
                yield (f"|{endpoint['group_name']}|")
        elif impacted_endpoints is not None:
            yield "This change has been scanned for critical changes"


class FooterSectionWriter(BaseSectionWriter):
    async def do_write_section(self, comparison, diff, changes, links):
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
    async def do_write_section(self, comparison, diff, changes, links):
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
    async def do_write_section(self, comparison, diff, changes, links):
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
        for li in lines:
            yield (li)
        yield ("```")


class FileSectionWriter(BaseSectionWriter):
    async def do_write_section(self, comparison, diff, changes, links):
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
                    get_totals_from_file_in_reports(base_report, path) or False,
                    get_totals_from_file_in_reports(head_report, path) or False,
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
            files_in_critical = set()
            if self.settings.get("show_critical_paths", False):
                all_files = set(f[1] for f in files_in_diff or []) | set(
                    c.path for c in changes or []
                )
                overlay = comparison.get_overlay(OverlayType.line_execution_count)
                files_in_critical = set(
                    overlay.search_files_for_critical_changes(all_files)
                )

            def tree_cell(typ, path, metrics, _=None):
                if path not in mentioned:
                    # mentioned: for files that are in diff and changes
                    mentioned.append(path)
                    return "| {rm}[{path}]({compare}/diff?src=pr&el=tree#diff-{hash}){rm}{file_tags} {metrics}".format(
                        rm="~~" if typ == "deleted" else "",
                        path=escape_markdown(ellipsis(path, 50, False)),
                        compare=links["pull"],
                        hash=b64encode(path.encode()).decode(),
                        metrics=metrics,
                        file_tags=" **Critical**" if path in files_in_critical else "",
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
                            get_totals_from_file_in_reports(base_report, change.path)
                            or False,
                            get_totals_from_file_in_reports(head_report, change.path)
                            or False,
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
    async def do_write_section(self, comparison, diff, changes, links):
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
                        "before": get_totals_from_file_in_reports(base_flags, name),
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
