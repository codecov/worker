import json
import re
from typing import Sequence

from shared.profiling import ProfilingDataFullAnalyzer, ProfilingSummaryDataAnalyzer
from shared.ribs import rustify_diff
from shared.storage.exceptions import FileNotInStorageError
from shared.yaml import UserYaml

from database.models.profiling import ProfilingCommit

sentinel = object()


def _get_latest_profiling_commit(comparison):
    db_session = comparison.head.commit.get_db_session()
    return (
        db_session.query(ProfilingCommit)
        .filter(
            ProfilingCommit.repoid == comparison.base.commit.repoid,
            ~ProfilingCommit.summarized_location.is_(None),
            ~ProfilingCommit.last_summarized_at.is_(None),
        )
        .order_by(ProfilingCommit.last_summarized_at.desc())
        .first()
    )


def _load_critical_path_report(comparison) -> ProfilingSummaryDataAnalyzer:
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


def _load_full_profiling_analyzer(comparison) -> ProfilingDataFullAnalyzer:
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
    def __init__(self, comparison, critical_path_report):
        self._comparison = comparison
        self._critical_path_report = critical_path_report
        self._profiling_analyzer = sentinel

    @classmethod
    def init_from_comparison(cls, comparison):
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
        repo = self._comparison.head.commit.repository
        repo_yaml = UserYaml.get_final_yaml(
            owner_yaml=repo.owner.yaml, repo_yaml=repo.yaml, ownerid=repo.owner.ownerid
        )
        if not repo_yaml.get("profiling") or not repo_yaml["profiling"].get(
            "critical_files_paths"
        ):
            return []
        critical_files_paths = repo_yaml["profiling"]["critical_files_paths"]
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

    async def find_impacted_endpoints(self):
        analyzer = self.full_analyzer
        if analyzer is None:
            return None
        diff = rustify_diff(await self._comparison.get_diff())
        return self.full_analyzer.find_impacted_endpoints(
            self._comparison.base.report.rust_report.get_report(),
            self._comparison.head.report.rust_report.get_report(),
            diff,
        )
