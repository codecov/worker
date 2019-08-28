import os
import logging
import sys
import gzip
import json

import minio
from minio.error import (ResponseError, BucketAlreadyOwnedByYou,
                         BucketAlreadyExists, NoSuchKey)
from io import BytesIO

from services.storage.base import BaseStorageService
from services.storage.exceptions import BucketAlreadyExistsError, FileNotInStorageError

log = logging.getLogger(__name__)


# Service class for interfacing with codecov's underlying storage layer, minio
class MinioStorageService(BaseStorageService):

    def __init__(self, minio_config):
        self.minio_config = minio_config
        log.debug("Connecting to minio with config %s", self.minio_config)

        self.minio_client = self.init_minio_client(
            self.minio_config['host'],
            self.minio_config['port'],
            self.minio_config['access_key_id'],
            self.minio_config['secret_access_key'],
            self.minio_config['verify_ssl']
        )
        log.debug("Done setting up minio client")

    def client(self):
        return self.minio_client if self.minio_client else None

    def init_minio_client(self, host, port, access_key, secret_key, verify_ssl):
        return minio.Minio(
            '{}:{}'.format(host, port),
            access_key=access_key,
            secret_key=secret_key,
            secure=verify_ssl
        )

    # writes the initial storage bucket to storage via minio.
    def create_root_storage(self, bucket_name='archive', region='us-east-1'):
        read_only_policy = {
            'Statement': [
                {
                    'Action': ['s3:GetObject'],
                    'Effect': 'Allow',
                    'Principal': {'AWS': ['*']},
                    'Resource': [f'arn:aws:s3:::{bucket_name}/*']
                }
            ],
            'Version': '2012-10-17'
        }
        try:
            if True:  # not self.minio_client.bucket_exists(bucket_name):
                log.debug("Making bucket on bucket %s on location %s", bucket_name, region)
                self.minio_client.make_bucket(bucket_name, location=region)
                log.debug("Setting policy")
                self.minio_client.set_bucket_policy(bucket_name, json.dumps(read_only_policy))
                log.debug("Done creating root storage")
                return {'name': bucket_name}
        # todo should only pass or raise
        except BucketAlreadyOwnedByYou:
            raise BucketAlreadyExistsError(f"Bucket {bucket_name} already exists")
        except BucketAlreadyExists:
            pass
        except ResponseError:
            raise

    # Writes a file to storage will gzip if not compressed already
    def write_file(self, bucket_name, path, data, reduced_redundancy=False, gzipped=False):
        if not gzipped:
            out = BytesIO()
            with gzip.GzipFile(fileobj=out, mode='w', compresslevel=9) as gz:
                if isinstance(data, str):
                    data = data.encode()
                gz.write(data)
        else:
            out = BytesIO(data)

        try:
            # get file size
            out.seek(0, os.SEEK_END)
            out_size = out.tell()

            # reset pos for minio reading.
            out.seek(0)

            headers = {'Content-Encoding': 'gzip'}
            if reduced_redundancy:
                headers['x-amz-storage-class'] = 'REDUCED_REDUNDANCY'
            self.minio_client.put_object(
                bucket_name, path, out, out_size,
                metadata=headers,
                content_type='text/plain')
            return True

        except ResponseError:
            raise
    """
        Retrieves object from path, appends data, writes back to path.
    """
    def append_to_file(self, bucket_name, path, data):

        try:
            file_contents = '\n'.join((self.read_file(bucket_name, path).decode(), data))
        except FileNotInStorageError:
            file_contents = data
        except ResponseError:
            raise
        return self.write_file(bucket_name, path, file_contents)

    def read_file(self, bucket_name, path):
        try:
            req = self.minio_client.get_object(bucket_name, path)
            data = BytesIO()
            for d in req.stream(32*1024):
                data.write(d)

            data.seek(0)
            return data.getvalue()
        except NoSuchKey:
            raise FileNotInStorageError(f"File {path} does not exist in {bucket_name}")
        except ResponseError:
            raise

    """
        Deletes file url in specified bucket.
        Return true on successful
        deletion, returns a ResponseError otherwise.
    """
    def delete_file(self, bucket_name, url):
        try:
            # delete a file given a bucket name and a url
            self.minio_client.remove_object(bucket_name, url)
            return True
        except ResponseError:
            raise

    def delete_files(self, bucket_name, urls=[]):
        try:
            for del_err in self.minio_client.remove_objects(bucket_name, urls):
                print("Deletion error: {}".format(del_err))
            return [True] * len(urls)
        except ResponseError:
            raise

    def list_folder_contents(self, bucket_name, prefix=None, recursive=True):
        return (
            self.object_to_dict(b) for b in self.minio_client.list_objects_v2(bucket_name, prefix, recursive)
        )

    def object_to_dict(self, obj):
        return {
            'name': obj.object_name,
            'size': obj.size
        }

    # TODO remove this function -- just using it for output during testing.
    def write(self, string, silence=False):
        if not silence:
            sys.stdout.write((string or '') + '\n')
