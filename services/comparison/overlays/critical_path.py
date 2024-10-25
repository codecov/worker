import json
import re
from typing import Self, Sequence

from asgiref.sync import async_to_sync
from cc_rustyribs import rustify_diff
from shared.profiling import ProfilingDataFullAnalyzer, ProfilingSummaryDataAnalyzer
from shared.storage.exceptions import FileNotInStorageError

from database.models.core import GITHUB_APP_INSTALLATION_DEFAULT_NAME
from database.models.profiling import ProfilingCommit
from services.repository import get_repo_provider_service
from services.yaml import get_current_yaml

sentinel = object()


def _get_latest_profiling_commit(comparison) -> ProfilingCommit | None:
    """
    @param comparison: ComparisonProxy (not imported due to circular imports)
    """
    if comparison.project_coverage_base.commit is None:
        return None
    db_session = comparison.head.commit.get_db_session()
    return (
        db_session.query(ProfilingCommit)
        .filter(
            ProfilingCommit.repoid == comparison.project_coverage_base.commit.repoid,
            ~ProfilingCommit.summarized_location.is_(None),
            ~ProfilingCommit.last_summarized_at.is_(None),
        )
        .order_by(ProfilingCommit.last_summarized_at.desc())
        .first()
    )


def _load_critical_path_report(
    comparison,
) -> ProfilingSummaryDataAnalyzer | None:
    """
    @param comparison: ComparisonProxy (not imported due to circular imports)
    """
    latest_profiling_commit = _get_latest_profiling_commit(comparison)
    if latest_profiling_commit is None:
        return None
    try:
        data = json.loads(
            comparison.get_archive_service().read_file(
                latest_profiling_commit.summarized_location
            )
        )
    except FileNotInStorageError:
        return None
    return ProfilingSummaryDataAnalyzer(data)


def _load_full_profiling_analyzer(
    comparison,
) -> ProfilingDataFullAnalyzer | None:
    """
    @param comparison: ComparisonProxy (not imported due to circular imports)
    """
    latest_profiling_commit = _get_latest_profiling_commit(comparison)
    if latest_profiling_commit is None:
        return None
    try:
        data = (
            comparison.get_archive_service()
            .read_file(latest_profiling_commit.joined_location)
            .decode()
        )
    except FileNotInStorageError:
        return None
    return ProfilingDataFullAnalyzer.load_from_json(data)


class CriticalPathOverlay(object):
    def __init__(
        self,
        comparison,
        critical_path_report: ProfilingSummaryDataAnalyzer | None,
    ) -> None:
        """
        @param comparison: ComparisonProxy (not imported due to circular imports)
        """
        self._comparison = comparison
        self._critical_path_report = critical_path_report
        self._profiling_analyzer = sentinel

    @classmethod
    def init_from_comparison(cls, comparison) -> Self:
        """
        @param comparison: ComparisonProxy (not imported due to circular imports)
        """
        return cls(
            comparison=comparison,
            critical_path_report=_load_critical_path_report(comparison),
        )

    @property
    def full_analyzer(self):
        if self._profiling_analyzer is sentinel:
            self._profiling_analyzer = _load_full_profiling_analyzer(self._comparison)
        return self._profiling_analyzer

    def _get_critical_files_from_yaml(self, filenames_to_search: Sequence[str]):
        """
        Get list of files in filenames_to_search that match the list of critical_file paths defined by the user in the YAML (under profiling.critical_files_paths)
        """
        current_yaml = self._comparison.comparison.current_yaml
        if current_yaml is None:
            repo = self._comparison.head.commit.repository
            gh_app_installation_name = (
                self._comparison.context.gh_app_installation_name
                or GITHUB_APP_INSTALLATION_DEFAULT_NAME
            )
            repo_provider = get_repo_provider_service(
                repo, installation_name_to_use=gh_app_installation_name
            )
            current_yaml = async_to_sync(get_current_yaml)(
                self._comparison.head.commit, repo_provider
            )
        if not current_yaml.get("profiling") or not current_yaml["profiling"].get(
            "critical_files_paths"
        ):
            return []
        critical_files_paths = current_yaml["profiling"]["critical_files_paths"]
        compiled_files_paths = [re.compile(path) for path in critical_files_paths]
        user_defined_critical_files = [
            file
            for file in filenames_to_search
            if any(map(lambda regex: regex.match(file), compiled_files_paths))
        ]
        return user_defined_critical_files

    def search_files_for_critical_changes(self, filenames_to_search: Sequence[str]):
        """
        Returns list of files considered critical in filenames_to_search.
        Critical files comes from 2 sources:
            1. Critical files from  self._critical_path_report (actually detected by impact analysis)
            2. critical files that match paths defined in the user YAML
        """
        critical_files_from_profiling = set()
        if self._critical_path_report:
            critical_files_from_profiling = set(filenames_to_search) & set(
                self._critical_path_report.get_critical_files_filenames()
            )
        critical_files_from_yaml = set(
            self._get_critical_files_from_yaml(filenames_to_search)
        )
        return list(critical_files_from_profiling | critical_files_from_yaml)

    def find_impacted_endpoints(self):
        analyzer = self.full_analyzer
        if analyzer is None:
            return None
        diff = rustify_diff(self._comparison.get_diff())
        return self.full_analyzer.find_impacted_endpoints(
            self._comparison.project_coverage_base.report.rust_report.get_report(),
            self._comparison.head.report.rust_report.get_report(),
            diff,
        )
