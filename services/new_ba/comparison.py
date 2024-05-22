from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from typing import Iterator, List, MutableSet, Optional, Tuple

from services.new_ba.report import (
    AssetReport,
    BundleAnalysisReport,
    BundleReport,
)
from services.new_ba.storage import BundleAnalysisReportLoader


class MissingBaseReportError(Exception):
    pass


class MissingHeadReportError(Exception):
    pass


class MissingBundleError(Exception):
    pass


@dataclass(frozen=True)
class BundleChange:
    """
    Info about how a bundle has changed between two different reports.
    """

    class ChangeType(Enum):
        ADDED = "added"
        REMOVED = "removed"
        CHANGED = "changed"

    bundle_name: str
    change_type: ChangeType
    size_delta: int


@dataclass(frozen=True)
class AssetChange:
    """
    Info about how an asset has changed between two different reports.
    """

    class ChangeType(Enum):
        ADDED = "added"
        REMOVED = "removed"
        CHANGED = "changed"

    asset_name: str
    change_type: ChangeType
    size_delta: int


AssetMatch = Tuple[Optional[AssetReport], Optional[AssetReport]]


class BundleComparison:
    def __init__(
        self, base_bundle_report: BundleReport, head_bundle_report: BundleReport
    ):
        self.base_bundle_report = base_bundle_report
        self.head_bundle_report = head_bundle_report

    def total_size_delta(self) -> int:
        base_size = self.base_bundle_report.total_size()
        head_size = self.head_bundle_report.total_size()
        return head_size - base_size

    def asset_changes(self) -> List[AssetChange]:
        # this groups assets by name
        # there can be multiple assets with the same name and we
        # need to try and match them across base and head reports
        base_asset_reports = defaultdict(set)
        for asset_report in self.base_bundle_report.asset_reports():
            base_asset_reports[asset_report.name].add(asset_report)
        head_asset_reports = defaultdict(set)
        for asset_report in self.head_bundle_report.asset_reports():
            head_asset_reports[asset_report.name].add(asset_report)

        # match bundles across base and head
        # (A, B) means that bundle A transformed to bundle B
        # (X, None) means that bundle X was deleted
        # (None, X) means that bundle X was added
        matches: List[AssetMatch] = []
        asset_names = []
        for asset_name, asset_reports in head_asset_reports.items():
            asset_names.append(asset_name)
            matches += self._match_assets(base_asset_reports[asset_name], asset_reports)
        for asset_name, asset_reports in base_asset_reports.items():
            if asset_name not in asset_names:
                matches += self._match_assets(asset_reports, [])

        changes = []
        for base_asset_report, head_asset_report in matches:
            if base_asset_report is None:
                change = AssetChange(
                    asset_name=head_asset_report.name,
                    change_type=AssetChange.ChangeType.ADDED,
                    size_delta=head_asset_report.size,
                )
            elif head_asset_report is None:
                change = AssetChange(
                    asset_name=base_asset_report.name,
                    change_type=AssetChange.ChangeType.REMOVED,
                    size_delta=-base_asset_report.size,
                )
            else:
                change = AssetChange(
                    asset_name=head_asset_report.name,
                    change_type=AssetChange.ChangeType.CHANGED,
                    size_delta=head_asset_report.size - base_asset_report.size,
                )
            changes.append(change)

        return changes

    def _match_assets(
        self,
        base_asset_reports: MutableSet[AssetReport],
        head_asset_reports: MutableSet[AssetReport],
    ) -> List[AssetMatch]:
        """
        The given base assets and head assets all have the same name.
        This method attempts to pick the most likely matching of assets between
        base and head (so as to track their changes through time).

        The current approach is fairly naive and just picks the asset with the
        closest size.  There are probably better ways of doing this that we can
        improve upon in the future.
        """
        n = max([len(base_asset_reports), len(head_asset_reports)])
        matches: List[AssetMatch] = []

        while len(matches) < n:
            if len(head_asset_reports) > 0:
                # we have an unmatched head asset
                head_asset_report = head_asset_reports.pop()

                if len(base_asset_reports) == 0:
                    # no more base assets to match against
                    matches.append((None, head_asset_report))
                else:
                    # try and find the most "similar" base asset
                    size_deltas = {
                        abs(head_asset_report.size - base_bundle.size): base_bundle
                        for base_bundle in base_asset_reports
                    }
                    min_delta = min(size_deltas.keys())
                    base_asset_report = size_deltas[min_delta]

                    matches.append((base_asset_report, head_asset_report))
                    base_asset_reports.remove(base_asset_report)
            elif len(base_asset_reports) > 0:
                # we have unmatched base assets and no more head assets
                base_asset_report = base_asset_reports.pop()
                matches.append((base_asset_report, None))
            else:
                # shouldn't ever get here
                raise Exception("incorrect asset matching logic")  # pragma: no cover

        return matches


class BundleAnalysisComparison:
    """
    Compares two different bundle analysis reports.
    """

    def __init__(
        self,
        loader: BundleAnalysisReportLoader,
        base_report_key: str,
        head_report_key: str,
    ):
        self.loader = loader
        self.base_report_key = base_report_key
        self.head_report_key = head_report_key

    @cached_property
    def base_report(self) -> BundleAnalysisReport:
        base_report = self.loader.load(self.base_report_key)
        if base_report is None:
            raise MissingBaseReportError()
        return base_report

    @cached_property
    def head_report(self) -> BundleAnalysisReport:
        head_report = self.loader.load(self.head_report_key)
        if head_report is None:
            raise MissingHeadReportError()
        return head_report

    def bundle_changes(self) -> Iterator[BundleChange]:
        """
        Returns a list of changes across the bundles in the base and head reports.
        """
        base_bundle_reports = {
            bundle_report.name: bundle_report
            for bundle_report in self.base_report.bundle_reports()
        }
        head_bundle_reports = {
            bundle_report.name: bundle_report
            for bundle_report in self.head_report.bundle_reports()
        }

        for bundle_name, head_bundle_report in head_bundle_reports.items():
            if bundle_name not in base_bundle_reports:
                yield BundleChange(
                    bundle_name=bundle_name,
                    change_type=BundleChange.ChangeType.ADDED,
                    size_delta=head_bundle_report.total_size(),
                )
            else:
                base_bundle_report = base_bundle_reports[bundle_name]
                del base_bundle_reports[bundle_name]
                size_delta = (
                    head_bundle_report.total_size() - base_bundle_report.total_size()
                )
                yield BundleChange(
                    bundle_name=bundle_name,
                    change_type=BundleChange.ChangeType.CHANGED,
                    size_delta=size_delta,
                )

        for bundle_name, base_bundle_report in base_bundle_reports.items():
            yield BundleChange(
                bundle_name=bundle_name,
                change_type=BundleChange.ChangeType.REMOVED,
                size_delta=-base_bundle_report.total_size(),
            )

    def bundle_comparison(self, bundle_name: str) -> BundleComparison:
        """
        More detailed comparison (about asset changes) for a particular bundle that
        exists both in the base and head reports.
        """
        base_bundle_report = self.base_report.bundle_report(bundle_name)
        head_bundle_report = self.head_report.bundle_report(bundle_name)
        if base_bundle_report is None or head_bundle_report is None:
            raise MissingBundleError()
        return BundleComparison(base_bundle_report, head_bundle_report)
