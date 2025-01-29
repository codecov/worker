import logging
from typing import List, Literal, TypedDict

import sentry_sdk
from asgiref.sync import async_to_sync
from django.template import loader
from shared.bundle_analysis import (
    BundleAnalysisComparison,
    BundleChange,
    MissingBundleError,
)
from shared.bundle_analysis.comparison import AssetChange, RouteChange
from shared.torngit.exceptions import TorngitClientError
from shared.validation.types import BundleThreshold

from services.bundle_analysis.notify.contexts.comment import (
    BundleAnalysisPRCommentNotificationContext,
)
from services.bundle_analysis.notify.helpers import (
    bytes_readable,
    get_github_app_used,
    is_bundle_change_within_configured_threshold,
)
from services.bundle_analysis.notify.messages import MessageStrategyInterface
from services.license import requires_license
from services.notification.notifiers.base import NotificationResult
from services.urls import get_bundle_analysis_pull_url, get_members_url

log = logging.getLogger(__name__)


class BundleRow(TypedDict):
    bundle_name: str
    bundle_size: str
    change_size_readable: str
    percentage_change_readable: str
    change_icon: str
    has_cached: bool
    is_change_outside_threshold: bool


class BundleRouteRow(TypedDict):
    route_name: str
    change_size_readable: str
    percentage_change_readable: str
    change_icon: str
    route_size: str


class ModuleData(TypedDict):
    module_name: str
    change_size_readable: str


class AssetData(TypedDict):
    asset_display_name_1: str
    asset_display_name_2: str
    change_size_readable: str
    percentage_change_readable: str
    change_icon: str
    asset_size_readable: str
    module_data: List[ModuleData]


class IndividualBundleData(TypedDict):
    bundle_name: str
    asset_data: List[AssetData]
    app_routes_data: List[BundleRouteRow]


class BundleCommentTemplateContext(TypedDict):
    pull_url: str
    total_size_delta: int
    total_size_readable: str
    total_percentage: str
    status_level: Literal["INFO"] | Literal["WARNING"] | Literal["ERROR"]
    warning_threshold_readable: str
    bundle_rows: list[BundleRow]
    has_cached_bundles: bool
    individual_bundle_data: dict[str, IndividualBundleData]


class UpgradeCommentTemplateContext(TypedDict):
    author_username: str
    is_saas: bool
    activation_link: str


class BundleAnalysisCommentMarkdownStrategy(MessageStrategyInterface):
    def build_message(
        self, context: BundleAnalysisPRCommentNotificationContext
    ) -> str | bytes:
        if context.should_use_upgrade_comment:
            return self.build_upgrade_message(context)
        else:
            return self.build_default_message(context)

    @sentry_sdk.trace
    def build_default_message(
        self, context: BundleAnalysisPRCommentNotificationContext
    ) -> str:
        try:
            pull = context.pull.database_pull
            repository_service = context.repository_service
            changed_files = async_to_sync(repository_service.get_pull_request_files)(
                pull.pullid
            )
        except Exception:
            changed_files = None
            log.error(
                "Unable to retrieve PR files",
                extra=dict(
                    commit=context.commit.commitid,
                    report_key=context.commit_report.external_id,
                    pullid=pull.pullid,
                ),
                exc_info=True,
            )

        template = loader.get_template("bundle_analysis_notify/bundle_comment.md")
        total_size_delta = context.bundle_analysis_comparison.total_size_delta
        warning_threshold = context.user_config.warning_threshold
        bundle_rows = self._create_bundle_rows(
            context.bundle_analysis_comparison, warning_threshold
        )

        individual_bundle_data = self._create_individual_bundle_data(
            context.bundle_analysis_comparison,
            changed_files,
            warning_threshold,
        )

        if warning_threshold.type == "absolute":
            warning_threshold_readable = bytes_readable(warning_threshold.threshold)
        else:
            warning_threshold_readable = str(round(warning_threshold.threshold)) + "%"
        context = BundleCommentTemplateContext(
            has_cached=any(row["is_cached"] for row in bundle_rows),
            bundle_rows=bundle_rows,
            pull_url=get_bundle_analysis_pull_url(pull=context.pull.database_pull),
            total_size_delta=total_size_delta,
            status_level=context.commit_status_level.name,
            total_percentage=str(
                round(context.bundle_analysis_comparison.percentage_delta, 2)
            )
            + "%",
            total_size_readable=bytes_readable(total_size_delta, show_negative=False),
            warning_threshold_readable=warning_threshold_readable,
            individual_bundle_data=individual_bundle_data,
        )
        return template.render(context)

    @sentry_sdk.trace
    def build_upgrade_message(
        self, context: BundleAnalysisPRCommentNotificationContext
    ) -> str:
        template = loader.get_template("bundle_analysis_notify/upgrade_comment.md")
        context = UpgradeCommentTemplateContext(
            activation_link=get_members_url(context.pull.database_pull),
            is_saas=not requires_license(),
            author_username=context.pull.provider_pull["author"].get("username"),
        )
        return template.render(context)

    @sentry_sdk.trace
    def send_message(
        self, context: BundleAnalysisPRCommentNotificationContext, message: str
    ) -> NotificationResult:
        pull = context.pull.database_pull
        repository_service = context.repository_service
        try:
            comment_id = pull.bundle_analysis_commentid
            if comment_id:
                async_to_sync(repository_service.edit_comment)(
                    pull.pullid, comment_id, message
                )
            else:
                res = async_to_sync(repository_service.post_comment)(
                    pull.pullid, message
                )
                pull.bundle_analysis_commentid = res["id"]
            return NotificationResult(
                notification_attempted=True,
                notification_successful=True,
                github_app_used=get_github_app_used(repository_service),
            )
        except TorngitClientError:
            log.error(
                "Error creating/updating PR comment",
                extra=dict(
                    commit=context.commit.commitid,
                    report_key=context.commit_report.external_id,
                    pullid=pull.pullid,
                ),
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="TorngitClientError",
            )

    def _create_bundle_rows(
        self,
        comparison: BundleAnalysisComparison,
        configured_threshold: BundleThreshold,
    ) -> list[BundleRow]:
        bundle_rows = []
        bundle_changes = comparison.bundle_changes()
        # Calculate bundle change data in one loop since bundle_changes is a generator
        for bundle_change in bundle_changes:
            # Define row table data
            bundle_name = bundle_change.bundle_name
            if bundle_change.change_type == BundleChange.ChangeType.REMOVED:
                size = "(removed)"
                is_cached = False
            else:
                head_bundle_report = comparison.head_report.bundle_report(bundle_name)
                size = bytes_readable(head_bundle_report.total_size())
                is_cached = head_bundle_report.is_cached()

            change_size = bundle_change.size_delta
            if change_size == 0:
                # Don't include bundles that were not changed in the table
                continue
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
                    is_cached=is_cached,
                    percentage_change_readable=f"{bundle_change.percentage_delta}%",
                    is_change_outside_threshold=(
                        not is_bundle_change_within_configured_threshold(
                            bundle_change, configured_threshold
                        )
                    ),
                )
            )

        return bundle_rows

    def _create_bundle_route_data(
        self,
        comparison: BundleAnalysisComparison,
        warning_threshold: BundleThreshold,
    ) -> dict[str, list[BundleRouteRow]]:
        """
        Translate BundleRouteComparison dict data into a template compatible dict data
        """
        bundle_route_data = {}
        changes_dict = comparison.bundle_routes_changes()

        for bundle_name, route_changes in changes_dict.items():
            rows = []
            for route_change in route_changes:
                change_size, size = (
                    route_change.size_delta,
                    bytes_readable(route_change.size_head),
                )

                if change_size == 0:
                    continue

                exceeds_threshold = (
                    warning_threshold.type == "percentage"
                    and route_change.percentage_delta > warning_threshold.threshold
                )
                bundle_display_name, icon = route_change.route_name, ""
                if route_change.change_type == RouteChange.ChangeType.ADDED:
                    icon = ":rocket:"
                    bundle_display_name = f"**{route_change.route_name}** _(New)_"
                elif route_change.change_type == RouteChange.ChangeType.REMOVED:
                    icon = ":wastebasket:"
                    bundle_display_name = (
                        f"~~**{route_change.route_name}**~~ _(Deleted)_"
                    )
                elif exceeds_threshold:
                    icon = ":warning:"

                rows.append(
                    BundleRouteRow(
                        route_name=bundle_display_name,
                        change_size_readable=bytes_readable(change_size),
                        percentage_change_readable=f"{route_change.percentage_delta}%",
                        change_icon=icon,
                        route_size=size,
                    )
                )
            bundle_route_data[bundle_name] = rows
        return bundle_route_data

    def _create_asset_data(
        self,
        comparison: BundleAnalysisComparison,
        bundle_name: str,
        changed_files: List[str] | None,
        warning_threshold: BundleThreshold,
    ) -> List[AssetData]:
        try:
            asset_data = []
            asset_comparisons = comparison.bundle_comparison(
                bundle_name
            ).asset_comparisons()
            for asset_comparison in asset_comparisons:
                asset_change = asset_comparison.asset_change()

                # If not change in size for the asset then we don't show it
                if asset_change.size_delta == 0:
                    continue

                # Determine what asset name styling and change icon to use
                asset_display_name_1 = f"```{asset_change.asset_name}```"
                asset_display_name_2 = asset_display_name_2 = (
                    f"**```{asset_change.asset_name}```**"
                )
                exceeds_threshold = (
                    warning_threshold.type == "percentage"
                    and asset_change.percentage_delta > warning_threshold.threshold
                )
                if asset_change.change_type == AssetChange.ChangeType.ADDED:
                    asset_display_name_1 = f"**{asset_display_name_1}** _(New)_"
                    change_icon = ":rocket:"
                elif asset_change.change_type == AssetChange.ChangeType.REMOVED:
                    asset_display_name_1 = f"~~**{asset_display_name_1}**~~ _(Deleted)_"
                    change_icon = ":wastebasket:"
                elif exceeds_threshold:
                    change_icon = ":warning:"
                else:
                    change_icon = ""

                modules = asset_comparison.contributing_modules(
                    pr_changed_files=changed_files
                )
                asset_data.append(
                    AssetData(
                        asset_display_name_1=asset_display_name_1,
                        asset_display_name_2=asset_display_name_2,
                        change_size_readable=bytes_readable(asset_change.size_delta),
                        percentage_change_readable=f"{asset_change.percentage_delta}%",
                        change_icon=change_icon,
                        asset_size_readable=bytes_readable(asset_change.size_head),
                        module_data=[
                            ModuleData(
                                module_name=f"```{module.name}```",
                                change_size_readable=bytes_readable(module.size),
                            )
                            for module in modules
                        ],
                    )
                )
            return asset_data
        except MissingBundleError:
            # Won't have assets changed comparisons if either head or base report doesn't have the bundle
            return []

    def _create_individual_bundle_data(
        self,
        comparison: BundleAnalysisComparison,
        changed_files: List[str] | None,
        warning_threshold: BundleThreshold,
    ) -> dict[str, IndividualBundleData]:
        data = {}
        bundle_route_data = self._create_bundle_route_data(
            comparison, warning_threshold
        )
        for bundle_name in bundle_route_data.keys():
            asset_data = self._create_asset_data(
                comparison, bundle_name, changed_files, warning_threshold
            )

            # Only create an entry for this bundle if the there's either app routes or asset changes
            if asset_data or bundle_route_data.get(bundle_name):
                data[bundle_name] = IndividualBundleData(
                    bundle_name=bundle_name,
                    asset_data=asset_data,
                    app_routes_data=bundle_route_data[bundle_name],
                )
        return data
