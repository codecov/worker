import logging
from io import BytesIO

from google.cloud import storage
from google.oauth2.service_account import Credentials

import google.cloud.exceptions

from services.storage.base import BaseStorageService
from services.storage.exceptions import BucketAlreadyExistsError, FileNotInStorageError

log = logging.getLogger(__name__)


class GCPStorageService(BaseStorageService):

    def __init__(self, gcp_config):
        self.config = gcp_config
        self.credentials = self.load_credentials(gcp_config)
        self.storage_client = storage.Client(
            project=self.credentials.project_id,
            credentials=self.credentials
        )

    def load_credentials(self, gcp_config):
        location = gcp_config.get('google_credentials_location')
        if location:
            return Credentials.from_service_account_file(filename=location)
        return Credentials.from_service_account_info(gcp_config)

    def get_blob(self, bucket_name, path):
        bucket = self.storage_client.get_bucket(bucket_name)
        return storage.Blob(path, bucket)

    def create_root_storage(self, bucket_name='archive', region='us-east-1'):
        """
            Creates root storage (or bucket_name, as in some terminologies)

        Args:
            bucket_name (str): The name of the bucket to be created (default: {'archive'})
            region (str): The region in which the bucket will be created (default: {'us-east-1'})

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        try:
            return self.storage_client.create_bucket(bucket_name)
        except google.cloud.exceptions.Conflict:
            raise BucketAlreadyExistsError(f"Bucket {bucket_name} already exists")

    def write_file(self, bucket_name, path, data, reduced_redundancy=False, gzipped=False):
        """
            Writes a new file with the contents of `data`
            (What happens if the file already exists?)


        Args:
            bucket_name (str): The name of the bucket for the file to be created on
            path (str): The desired path of the file
            data (str): The data to be written to the file
            reduced_redundancy (bool): Whether a reduced redundancy mode should be used (default: {False})
            gzipped (bool): Whether the file should be gzipped on write (default: {False})

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        blob = self.get_blob(bucket_name, path)
        blob.upload_from_string(data)
        return True

    def append_to_file(self, bucket_name, path, data):
        """
            Appends more content to the file `path`
            (What happens if the file doesn't exist?)

            Note that this method assumes some non-bytes and instead decodable structure
                at the file

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The desired path of the file
            data (str): The data to be appended to the file

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        file_contents = '\n'.join((self.read_file(bucket_name, path).decode(), data))
        return self.write_file(bucket_name, path, file_contents)

    def read_file(self, bucket_name, path):
        """Reads the content of a file

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The path of the file

        Raises:
            NotImplementedError: If the current instance did not implement this method
            FileNotInStorageError: If the file does not exist

        Returns:
            bytes : The contents of that file, still encoded as bytes
        """
        blob = self.get_blob(bucket_name, path)
        data = BytesIO()
        try:
            blob.download_to_file(data)
        except google.cloud.exceptions.NotFound:
            raise FileNotInStorageError(f"File {path} does not exist in {bucket_name}")
        data.seek(0)
        return data.getvalue()

    def delete_file(self, bucket_name, path):
        """Deletes a single file from the storage (what happens if the file doesnt exist?)

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The path of the file to be deleted

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        blob = self.get_blob(bucket_name, path)
        try:
            blob.delete()
        except google.cloud.exceptions.NotFound:
            raise FileNotInStorageError(f"File {path} does not exist in {bucket_name}")
        return True

    def delete_files(self, bucket_name, paths=[]):
        """Batch deletes a list of files from a given bucket
            (what happens to the files that don't exist?)

        Args:
            bucket_name (str): The name of the bucket for the file lives
            paths (list): A list of the paths to be deletes (default: {[]})

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        raise NotImplementedError()

    def list_folder_contents(self, bucket_name, prefix=None, recursive=True):
        """List the contents of a specific folder

        Args:
            bucket_name (str): The name of the bucket for the file lives
            prefix: The prefix of the files to be listed (default: {None})
            recursive: Whether the listing should be recursive (default: {True})

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        raise NotImplementedError()
