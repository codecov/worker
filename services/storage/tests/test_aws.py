import pytest
import vcr

from tests.base import BaseTestCase
from services.storage.aws import AWSStorageService
from services.storage.exceptions import BucketAlreadyExistsError, FileNotInStorageError

aws_config = {
    "resource": "s3",
    "aws_access_key_id": "testvq4qkpw5e6exmeyb",
    "aws_secret_access_key": "testu2n7vttpqmw25saq043ngjomvaih878i1b11",
    "region_name": "us-east-1"
}

class TestAWSStorageService(BaseTestCase):
    
    def test_create_bucket(self):
        storage = AWSStorageService(
            aws_config
        )
        bucket_name = 'felipearchivetest'
        res = storage.create_root_storage(bucket_name=bucket_name)
        assert res['name'] == 'felipearchivetest'
    
    def test_create_bucket_at_region(self):
        storage = AWSStorageService(
            aws_config
        )
        bucket_name = 'felipearchivetestw'
        res = storage.create_root_storage(bucket_name=bucket_name, region='us-west-1')
        assert res['name'] == 'felipearchivetestw'

    def test_create_bucket_already_exists(self):
        storage = AWSStorageService(
            aws_config
        )
        bucket_name = 'felipearchivetest'
        with pytest.raises(BucketAlreadyExistsError):
            storage.create_root_storage(bucket_name=bucket_name)

    def test_create_bucket_already_exists_at_region(self):
        storage = AWSStorageService(
            aws_config
        )
        bucket_name = 'felipearchivetestw'
        with pytest.raises(BucketAlreadyExistsError):
            storage.create_root_storage(bucket_name=bucket_name, region='us-west-1')

    def test_write_then_read_file(self):
        storage = AWSStorageService(
            aws_config
        )
        path = 'test_write_then_read_file/result'
        data = 'lorem ipsum dolor test_write_then_read_file á'
        bucket_name = 'felipearchivetest'
        writing_result = storage.write_file(bucket_name=bucket_name, path=path, data=data)
        assert writing_result
        reading_result = storage.read_file(bucket_name=bucket_name, path=path)
        assert reading_result.decode() == data

    def test_write_then_append_then_read_file(self):
        storage = AWSStorageService(
            aws_config
        )
        path = 'test_write_then_append_then_read_file/result'
        data = 'lorem ipsum dolor test_write_then_read_file á'
        second_data = 'mom, look at me, appending data'
        bucket_name = 'felipearchivetest'
        writing_result = storage.write_file(bucket_name, path, data)
        assert writing_result
        second_writing_result = storage.append_to_file(bucket_name, path, second_data)
        assert second_writing_result
        reading_result = storage.read_file(bucket_name, path)
        assert reading_result.decode() == '\n'.join([data, second_data])

    def test_delete_file(self):
        storage = AWSStorageService(
            aws_config
        )
        path = 'test_delete_file/result2'
        data = 'lorem ipsum dolor test_write_then_read_file á'
        bucket_name = 'felipearchivetest'
        writing_result = storage.write_file(bucket_name=bucket_name, path=path, data=data)
        assert writing_result
        delete_result = storage.delete_file(bucket_name=bucket_name, path=path)
        assert delete_result
        with pytest.raises(FileNotFoundError):
            reading_result = storage.read_file(bucket_name=bucket_name, path=path)

    def test_batch_delete_files(self):
        storage = AWSStorageService(
            aws_config
        )
        path_1 = 'test_batch_delete_files/result1.txt'
        path_2 = 'test_batch_delete_files/result2.txt'
        path_3 = 'test_batch_delete_files/result3.txt'
        paths = [path_1, path_2, path_3]
        data = 'lorem ipsum dolor test_write_then_read_file á'
        bucket_name = 'felipearchivetest'
        writing_result_1 = storage.write_file(bucket_name=bucket_name, path=path_1, data=data)
        assert writing_result_1
        writing_result_3 = storage.write_file(bucket_name=bucket_name, path=path_3, data=data)
        assert writing_result_3
        delete_result = storage.delete_files(bucket_name=bucket_name, paths=paths)
        assert delete_result == [True, True, True]
        for p in paths:
            with pytest.raises(FileNotFoundError):
                storage.read_file(bucket_name=bucket_name, path=p)

    def test_list_folder_contents(self):
        storage = AWSStorageService(
            aws_config
        )
        path_1 = 'felipe/test_list_folder_contents/result_1.txt'
        path_2 = 'felipe/test_list_folder_contents/result_2.txt'
        path_3 = 'felipe/test_list_folder_contents/result_3.txt'
        path_4 = 'felipe/test_list_folder_contents/f1/result_4.txt'
        path_5 = 'felipe/test_list_folder_contents/f1/result_5.txt'
        path_6 = 'felipe/test_list_folder_contents/f1/result_6.txt'
        paths = [path_1, path_2, path_3, path_4, path_5, path_6]
        bucket_name = 'felipearchivetest'
        for i, p in enumerate(paths):
            data = f"Lorem ipsum on file {p} for {i * 'po'}"
            storage.write_file(bucket_name=bucket_name, path=p, data=data)
        results_1 = list(storage.list_folder_contents(bucket_name=bucket_name, prefix='felipe/test_list_folder_contents'))
        expected_result_1 = [
            {'name': path_1, 'size': 70}, 
            {'name': path_2, 'size': 72}, 
            {'name': path_3, 'size': 74},
            {'name': path_4, 'size': 79},
            {'name': path_5, 'size': 81},
            {'name': path_6, 'size': 83}
        ]
        assert sorted(expected_result_1, key=lambda x: x['size']) == sorted(results_1, key=lambda x: x['size'])
        results_2 = list(storage.list_folder_contents(bucket_name=bucket_name, prefix='felipe/test_list_folder_contents/f1'))
        expected_result_2 = [
            {'name': path_4, 'size': 79},
            {'name': path_5, 'size': 81},
            {'name': path_6, 'size': 83}
        ]
        assert sorted(expected_result_2, key=lambda x: x['size']) == sorted(results_2, key=lambda x: x['size'])