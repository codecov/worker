import hashlib
import json
from typing import Dict

from shared.reports.resources import Report

from database.models.core import Repository
from database.models.reports import CommitReport
from services.archive import ArchiveService
from services.report.report_builder import SpecialLabelsEnum


class LabelsIndexService(object):
    _archive_client: ArchiveService
    commit_report_code: str
    commit_sha: str
    loaded_hash: str

    @classmethod
    def default_labels_index(cls):
        return {0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label}

    @classmethod
    def from_commit_report(cls, commit_report: CommitReport):
        return cls(
            repository=commit_report.commit.repository,
            commit_sha=commit_report.commit.commitid,
            commit_report_code=commit_report.code,
        )

    def __init__(
        self, repository: Repository, commit_sha: str, commit_report_code: str
    ) -> None:
        self._archive_client = ArchiveService(repository=repository)
        self.commit_report_code = commit_report_code
        self.commit_sha = commit_sha
        self.loaded_hash = None

    def carryforward_label_idx(self, new_report: Report):
        """Sets the labels_index for this commit in another report.
        The other report can then save this index by creating
        a LabelsIndexService instance for itself.
        """
        my_index = self._get_label_idx()

        if my_index:
            # The current report has labels in the index
            # And we will copy the index to the new commit
            new_report.set_label_idx(my_index)

    def _get_label_idx(self) -> Dict[int, str]:
        # Load label index from storage
        # JSON uses strings are keys, but we are using ints.
        map_with_str_keys = self._archive_client.read_label_index(
            self.commit_sha, self.commit_report_code
        )
        self.loaded_hash = hashlib.sha1(
            json.dumps(map_with_str_keys).encode()
        ).hexdigest()
        return {int(k): v for k, v in map_with_str_keys.items()}

    def set_label_idx(self, report: Report) -> None:
        if report.labels_index is not None:
            raise Exception(
                "Trying to set labels_index of Report, but it's already set"
            )
        loaded_index = self._get_label_idx()
        report.set_label_idx(loaded_index)

    def save_and_unset_label_idx(self, report: Report) -> None:
        # Write the updated index back into storage
        # ! Only if there are changes to it
        current_hash = hashlib.sha1(
            json.dumps(report.labels_index).encode()
        ).hexdigest()
        if current_hash != self.loaded_hash:
            self._archive_client.write_label_index(
                self.commit_sha, report.labels_index, self.commit_report_code
            )
        # Remove reference to label index in the report
        # so it is collected by the garbage collector
        report.unset_label_idx()
