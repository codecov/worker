from typing import TypedDict

from django.template import loader
from shared.bundle_analysis import (
    BundleAnalysisComparison,
    BundleChange,
)

from services.bundle_analysis.notify.contexts.comment import (
    BundleAnalysisCommentNotificationContext,
)
from services.bundle_analysis.notify.helpers import bytes_readable
from services.urls import get_bundle_analysis_pull_url


class BundleRow(TypedDict):
    bundle_name: str
    bundle_size: str
    change_size_readable: str
    change_icon: str


class BundleCommentTemplateContext(TypedDict):
    pull_url: str
    total_size_delta: int
    total_size_readable: str
    bundle_rows: list[BundleRow]


def _create_bundle_rows(
    comparison: BundleAnalysisComparison,
) -> tuple[BundleRow]:
    bundle_rows = []
    bundle_changes = comparison.bundle_changes()
    # Calculate bundle change data in one loop since bundle_changes is a generator
    for bundle_change in bundle_changes:
        # Define row table data
        bundle_name = bundle_change.bundle_name
        if bundle_change.change_type == BundleChange.ChangeType.REMOVED:
            size = "(removed)"
        else:
            head_bundle_report = comparison.head_report.bundle_report(bundle_name)
            size = bytes_readable(head_bundle_report.total_size())

        change_size = bundle_change.size_delta
        icon = ""
        if change_size > 0:
            icon = ":arrow_up:"
        elif change_size < 0:
            icon = ":arrow_down:"

        bundle_rows.append(
            BundleRow(
                bundle_name=bundle_name,
                bundle_size=size,
                change_size_readable=bytes_readable(change_size),
                change_icon=icon,
            )
        )

    return bundle_rows


# TODO: Turn into class following some interface
def build_message(context: BundleAnalysisCommentNotificationContext) -> str:
    template = loader.get_template("bundle_analysis_notify/bundle_comment.md")
    total_size_delta = context.bundle_analysis_comparison.total_size_delta
    context = BundleCommentTemplateContext(
        bundle_rows=_create_bundle_rows(context.bundle_analysis_comparison),
        pull_url=get_bundle_analysis_pull_url(pull=context.pull.database_pull),
        total_size_delta=total_size_delta,
        total_size_readable=bytes_readable(total_size_delta),
    )
    return template.render(context=context)
