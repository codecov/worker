from shared.reports.resources import Report

from database.models.reports import CommitReport
from services.archive import ArchiveService


class LabelsIndexService(object):
    _archive_client: ArchiveService

    def __init__(self, commit_report: CommitReport) -> None:
        self.commit_report = commit_report
        self._archive_client = ArchiveService(
            repository=commit_report.commit.repository
        )
        self.commit_sha = commit_report.commit.commitid

    def set_label_idx(self, report: Report) -> None:
        if report._labels_index is not None:
            raise Exception(
                "Trying to set labels_index of Report, but it's already set"
            )
        # Load label index from storage
        # JSON uses strings are keys, but we are using ints.
        map_with_str_keys = self._archive_client.read_label_index(
            self.commit_sha, self.commit_report.code
        )
        loaded_index = {int(k): v for k, v in map_with_str_keys.items()}
        report.set_label_idx(loaded_index)

    def unset_label_idx(self, report: Report) -> None:
        # Write the updated index back into storage
        self._archive_client.write_label_index(
            self.commit_sha, report._labels_index, self.commit_report.code
        )
        # Remove reference to it
        report.unset_label_idx()
