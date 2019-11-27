import logging

from datetime import datetime
from hashlib import md5
from base64 import b16encode
from enum import Enum

from covreports.config import get_config
from helpers.metrics import metrics
from covreports.storage import get_appropriate_storage_service
from covreports.storage.exceptions import BucketAlreadyExistsError

log = logging.getLogger(__name__)


class MinioEndpoints(Enum):
    chunks = '{version}/repos/{repo_hash}/commits/{commitid}/chunks.txt'
    reports_json = '{version}/repos/{repo_hash}/commits/{commitid}/report.json'
    raw = 'v4/raw/{date}/{repo_hash}/{commit_sha}/{reportid}.txt'

    def get_path(self, **kwaargs):
        return self.value.format(**kwaargs)


# Service class for performing archive operations. Meant to work against the
# underlying StorageService
class ArchiveService(object):

    """
    The root level of the archive. In s3 terms,
    this would be the name of the bucket
    """
    root = None

    """
    Region where the storage is located.
    """
    region = None

    """
    A hash key of the repo for internal storage
    """
    storage_hash = None

    """
    Boolean. True if enterprise, False if not.
    """
    enterprise = False

    def __init__(self, repository, bucket=None):
        if bucket is None:
            self.root = get_config('services', 'minio', 'bucket', default='archive')
        else:
            self.root = bucket
        self.region = get_config('services', 'minio', 'region', default='us-east-1')
        self.enterprise = bool(get_config('setup', 'enterprise_license'))

        self.storage = get_appropriate_storage_service()
        log.debug("Getting archive hash")
        self.storage_hash = self.get_archive_hash(repository)

        # create storage based on the root, this will throw acceptable
        # exceptions if the bucket exists. ResponseError if it doesn't.
        # log.debug("Creating root storage")
        # try:
        #     self.storage.create_root_storage(self.root, self.region)
        # except BucketAlreadyExistsError:
        #     pass
        # log.debug("Created root storage")

    """
    Accessor for underlying StorageService. You typically shouldn't need
    this for anything.
    """
    def storage_client(self):
        return self.storage

    """
    Getter. Returns true if the current configuration is enterprise.
    """
    def is_enterprise(self):
        return self.enterprise

    """
    Generates a hash key from repo specific information.
    Provides slight obfuscation of data in minio storage
    """
    @classmethod
    def get_archive_hash(cls, repository):
        _hash = md5()
        hash_key = get_config('services', 'minio', 'hash_key')
        val = ''.join(map(str, (
            repository.repoid,
            repository.service,
            repository.service_id,
            hash_key
        ))).encode()
        _hash.update(val)
        return b16encode(_hash.digest()).decode()

    """
    Grabs path from storage, adds data to path object
    writes back to path, overwriting the original contents
    """
    def update_archive(self, path, data):
        self.storage.append_to_file(self.root, path, data)

    """
    Writes a generic file to the archive -- it's typically recommended to
    not use this in lieu of the convenience methods write_raw_upload and
    write_chunks
    """
    def write_file(self, path, data, reduced_redundancy=False, gzipped=False):
        self.storage.write_file(
            self.root, path, data, reduced_redundancy=reduced_redundancy, gzipped=gzipped)

    """
    Convenience write method, writes a raw upload to a destination.
    Returns the path it writes.
    """
    def write_raw_upload(self, commit_sha, report_id, data, gzipped=False):
        # create a custom report path for a raw upload.
        # write the file.
        path = '/'.join((
            'v4/raw',
            datetime.now().strftime('%Y-%m-%d'),
            self.storage_hash,
            commit_sha,
            '%s.txt' % report_id
        ))

        self.write_file(path, data, gzipped=gzipped)

        return path

    """
    Convenience method to write a chunks.txt file to storage.
    """
    def write_chunks(self, commit_sha, data):
        path = MinioEndpoints.chunks.get_path(
            version='v4',
            repo_hash=self.storage_hash,
            commitid=commit_sha
        )

        self.write_file(path, data)
        return path

    """
    Generic method to read a file from the archive
    """
    @metrics.timer('services.archive.read_file')
    def read_file(self, path):
        contents = self.storage.read_file(self.root, path)
        return contents.decode(errors="replace")

    """
    Generic method to delete a file from the archive.
    """
    def delete_file(self, path):
        self.storage.delete_file(self.root, path)

    """
    Deletes an entire repository's contents
    """
    def delete_repo_files(self):
        path = 'v4/repos/{}'.format(self.storage_hash)
        objects = self.storage.list_folder_contents(self.root, path)
        for obj in objects:
            self.storage.delete_file(self.root, obj.object_name)
    """
    Convenience method to read a chunks file from the archive.
    """
    def read_chunks(self, commit_sha):

        path = MinioEndpoints.chunks.get_path(
            version='v4',
            repo_hash=self.storage_hash,
            commitid=commit_sha
        )

        return self.read_file(path)

    """
    Delete a chunk file from the archive
    """
    def delete_chunk_from_archive(self, commit_sha):
        path = 'v4/repos/{}/commits/{}/chunks.txt'.format(
            self.storage_hash, commit_sha
        )

        self.delete_file(path)
