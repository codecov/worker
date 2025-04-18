import json
import logging
from base64 import b16encode
from datetime import datetime
from enum import Enum
from hashlib import md5

import sentry_sdk
import shared.storage
from shared.config import get_config
from shared.utils.ReportEncoder import ReportEncoder

from helpers.metrics import metrics

log = logging.getLogger(__name__)


class MinioEndpoints(Enum):
    chunks = "{version}/repos/{repo_hash}/commits/{commitid}/{chunks_file_name}.txt"
    json_data = "{version}/repos/{repo_hash}/commits/{commitid}/json_data/{table}/{field}/{external_id}.json"
    json_data_no_commit = (
        "{version}/repos/{repo_hash}/json_data/{table}/{field}/{external_id}.json"
    )
    raw = "v4/raw/{date}/{repo_hash}/{commit_sha}/{reportid}.txt"
    computed_comparison = "{version}/repos/{repo_hash}/comparisons/{comparison_id}.json"

    def get_path(self, **kwaargs) -> str:
        return self.value.format(**kwaargs)


# Service class for performing archive operations. Meant to work against the
# underlying StorageService
class ArchiveService(object):
    root: str
    """
    The root level of the archive. In s3 terms,
    this would be the name of the bucket
    """

    storage_hash: str
    """
    A hash key of the repo for internal storage
    """

    def __init__(self, repository, bucket=None) -> None:
        if bucket is None:
            self.root = get_config("services", "minio", "bucket", default="archive")
        else:
            self.root = bucket
        self.storage = shared.storage.get_appropriate_storage_service(repository.repoid)
        log.debug("Getting archive hash")
        self.storage_hash = self.get_archive_hash(repository)

    def get_now(self) -> datetime:
        return datetime.now()

    @classmethod
    def get_archive_hash(cls, repository) -> str:
        """
        Generates a hash key from repo specific information.
        Provides slight obfuscation of data in minio storage
        """
        _hash = md5()
        hash_key = get_config("services", "minio", "hash_key")
        val = "".join(
            map(
                str,
                (
                    repository.repoid,
                    repository.service,
                    repository.service_id,
                    hash_key,
                ),
            )
        ).encode()
        _hash.update(val)
        return b16encode(_hash.digest()).decode()

    @sentry_sdk.trace
    def write_file(
        self, path, data, reduced_redundancy=False, *, is_already_gzipped=False
    ) -> None:
        """
        Writes a generic file to the archive -- it's typically recommended to
        not use this in lieu of the convenience method `write_chunks`
        """
        self.storage.write_file(
            self.root,
            path,
            data,
            reduced_redundancy=reduced_redundancy,
            is_already_gzipped=is_already_gzipped,
        )

    def write_computed_comparison(self, comparison, data) -> str:
        path = MinioEndpoints.computed_comparison.get_path(
            version="v4", repo_hash=self.storage_hash, comparison_id=comparison.id
        )
        self.write_file(path, json.dumps(data))
        return path

    def write_json_data_to_storage(
        self,
        commit_id,
        table: str,
        field: str,
        external_id: str,
        data: dict,
        *,
        encoder=ReportEncoder,
    ):
        if commit_id is None:
            # Some classes don't have a commit associated with them
            # For example Pull belongs to multiple commits.
            path = MinioEndpoints.json_data_no_commit.get_path(
                version="v4",
                repo_hash=self.storage_hash,
                table=table,
                field=field,
                external_id=external_id,
            )
        else:
            path = MinioEndpoints.json_data.get_path(
                version="v4",
                repo_hash=self.storage_hash,
                commitid=commit_id,
                table=table,
                field=field,
                external_id=external_id,
            )
        stringified_data = json.dumps(data, cls=encoder)
        self.write_file(path, stringified_data)
        return path

    def write_chunks(self, commit_sha, data, report_code=None) -> str:
        """
        Convenience method to write a chunks.txt file to storage.
        """
        chunks_file_name = report_code if report_code is not None else "chunks"
        path = MinioEndpoints.chunks.get_path(
            version="v4",
            repo_hash=self.storage_hash,
            commitid=commit_sha,
            chunks_file_name=chunks_file_name,
        )

        self.write_file(path, data)
        return path

    @sentry_sdk.trace
    def read_file(self, path: str) -> bytes:
        """
        Generic method to read a file from the archive
        """
        with metrics.timer("services.archive.read_file") as t:
            contents = self.storage.read_file(self.root, path)
        log.debug(
            "Downloaded file", extra=dict(timing_ms=t.ms, content_len=len(contents))
        )
        return contents

    @sentry_sdk.trace
    def delete_file(self, path) -> None:
        """
        Generic method to delete a file from the archive.
        """
        self.storage.delete_file(self.root, path)

    def read_chunks(self, commit_sha, report_code=None) -> str:
        """
        Convenience method to read a chunks file from the archive.
        """
        chunks_file_name = report_code if report_code is not None else "chunks"
        path = MinioEndpoints.chunks.get_path(
            version="v4",
            repo_hash=self.storage_hash,
            commitid=commit_sha,
            chunks_file_name=chunks_file_name,
        )

        return self.read_file(path).decode(errors="replace")
