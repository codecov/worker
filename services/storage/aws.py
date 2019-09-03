import logging
import boto3

from botocore.exceptions import ClientError

from io import BytesIO

from services.storage.base import BaseStorageService
from services.storage.exceptions import BucketAlreadyExistsError, FileNotInStorageError

log = logging.getLogger(__name__)


class AWSStorageService(BaseStorageService):

    def __init__(self, aws_config):
        self.config = aws_config
        self.storage_client = boto3.client(
            aws_config.get('resource'),
            aws_access_key_id=aws_config.get('aws_access_key_id'),
            aws_secret_access_key=aws_config.get('aws_secret_access_key'),
            region_name=aws_config.get('region_name')
        )

    def create_root_storage(self, bucket_name='archive', region='us-east-1'):
        """
            Creates root storage (or bucket, as in some terminologies)

        Args:
            bucket_name (str): The name of the bucket to be created (default: {'archive'})
            region (str): The region in which the bucket will be created (default: {'us-east-1'})

        Raises:
            BucketAlreadyExistsError: If the bucket already exists
        """
        
        if region == 'us-east-1':
            try:
                self.storage_client.head_bucket(Bucket=bucket_name)
                raise BucketAlreadyExistsError(f"Bucket {bucket_name} already exists")
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    self.storage_client.create_bucket(Bucket=bucket_name)
        else:
            try:
                location = {'LocationConstraint': region}
                self.storage_client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration=location
                )
            except ClientError as e:
                if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
                    raise BucketAlreadyExistsError(f"Bucket {bucket_name} already exists")     
        return {
                    'name': bucket_name
                }

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
        
        """
        storage_class = 'REDUCED_REDUNDANCY' if reduced_redundancy else 'STANDARD'
        self.storage_client.put_object(
            Bucket=bucket_name, 
            Key=path, 
            Body=data
        )
        return True

    def append_to_file(self, bucket_name, path, data):
        """
            Appends more content to the file `path`
            (What happens if the file doesn't exist?)

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The desired path of the file
            data (str): The data to be appended to the file

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        try:
            file_contents = '\n'.join((self.read_file(bucket_name, path).decode(), data))
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                file_contents = data
        return self.write_file(bucket_name=bucket_name, path=path, data=file_contents)
   
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
        try:
            obj = self.storage_client.get_object(Bucket=bucket_name, Key=path)
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                raise FileNotFoundError(f"File {path} does not exist in {bucket_name}")
        data = BytesIO(obj['Body'].read())
        data.seek(0)
        return data.getvalue()

    def delete_file(self, bucket_name, path):
        """Deletes a single file from the storage

        Note: Not all implementations raise a FileNotInStorageError
            if the file is not already there in the first place.
            It seems that minio & AWS, for example, returns a 204 regardless.
            So while you should prepare for a FileNotInStorageError,
            know that if it is not raise, it doesn't mean the file
            was there beforehand.

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The path of the file to be deleted

        Raises:
            FileNotInStorageError: If the file does not exist

        Returns:
            bool: True if the deletion was succesful
        """
        try:
            response = self.storage_client.delete_object(Bucket=bucket_name, Key=path)
            return True
        except ClientError as e:
            raise 

    def delete_files(self, bucket_name, paths=[]):
        """Batch deletes a list of files from a given bucket
            (what happens to the files that don't exist?)

        Args:
            bucket_name (str): The name of the bucket for the file lives
            paths (list): A list of the paths to be deletes (default: {[]})

        Raises:
            NotImplementedError: If the current instance did not implement this method

        Returns:
            list: A list of booleans, where each result indicates whether that file was deleted
                successfully
        """
        objects_to_delete = {
            'Objects': [{'Key': key} for key in paths]
        }
        try:
            response = self.storage_client.delete_objects(
                Bucket=bucket_name,
                Delete=objects_to_delete
            )
        except ClientError as e:
            raise
        deletes = [error.get('Key') for error in response.get('Deleted')]
        return [key in deletes for key in paths]

    def list_folder_contents(self, bucket_name, prefix=None, recursive=True):
        """List the contents of a specific folder

        Args:
            bucket_name (str): The name of the bucket for the file lives
            prefix: The prefix of the files to be listed (default: {None})
            recursive: Whether the listing should be recursive (default: {True})

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        try:
            response = self.storage_client.list_objects(
                Bucket=bucket_name,
                Prefix=prefix
            )
        except ClientError as e:
            raise
        contents = response.get('Contents')
        return [{'name': content.get('Key'), 'size': content.get('Size')} for content in contents]
