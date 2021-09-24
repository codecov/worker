import json
from typing import Sequence

from shared.profiling import ProfilingDataAnalyzer
from shared.storage.exceptions import FileNotInStorageError

from database.models.profiling import ProfilingCommit


def _get_latest_profiling_commit(comparison):
    db_session = comparison.head.commit.get_db_session()
    return (
        db_session.query(ProfilingCommit)
        .filter(
            ProfilingCommit.repoid == comparison.base.commit.repoid,
            ~ProfilingCommit.summarized_location.is_(None),
        )
        .order_by(ProfilingCommit.last_summarized_at.desc())
        .first()
    )


def _load_critical_path_report(comparison) -> ProfilingDataAnalyzer:
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
    return ProfilingDataAnalyzer(data)


class CriticalPathOverlay(object):
    def __init__(self, comparison, critical_path_report):
        self._comparison = comparison
        self._critical_path_report = critical_path_report

    @classmethod
    def init_from_comparison(cls, comparison):
        return cls(
            comparison=comparison,
            critical_path_report=_load_critical_path_report(comparison),
        )

    def search_files_for_critical_changes(self, filenames_to_search: Sequence[str]):
        if self._critical_path_report is None:
            return []
        return set(filenames_to_search) & set(
            self._critical_path_report.get_critical_files_filenames()
        )
