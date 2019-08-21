import pytest

from tests.base import BaseTestCase
from services.storage.gcp import GCPStorageService
from services.storage.exceptions import BucketAlreadyExistsError, FileNotInStorageError

# DONT WORRY, this is generated for the purposes of validation, and is not the real
# one on which the code ran
fake_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQDCFqq2ygFh9UQU/6PoDJ6L9e4ovLPCHtlBt7vzDwyfwr3XGxln
0VbfycVLc6unJDVEGZ/PsFEuS9j1QmBTTEgvCLR6RGpfzmVuMO8wGVEO52pH73h9
rviojaheX/u3ZqaA0di9RKy8e3L+T0ka3QYgDx5wiOIUu1wGXCs6PhrtEwICBAEC
gYBu9jsi0eVROozSz5dmcZxUAzv7USiUcYrxX007SUpm0zzUY+kPpWLeWWEPaddF
VONCp//0XU8hNhoh0gedw7ZgUTG6jYVOdGlaV95LhgY6yXaQGoKSQNNTY+ZZVT61
zvHOlPynt3GZcaRJOlgf+3hBF5MCRoWKf+lDA5KiWkqOYQJBAMQp0HNVeTqz+E0O
6E0neqQDQb95thFmmCI7Kgg4PvkS5mz7iAbZa5pab3VuyfmvnVvYLWejOwuYSp0U
9N8QvUsCQQD9StWHaVNM4Lf5zJnB1+lJPTXQsmsuzWvF3HmBkMHYWdy84N/TdCZX
Cxve1LR37lM/Vijer0K77wAx2RAN/ppZAkB8+GwSh5+mxZKydyPaPN29p6nC6aLx
3DV2dpzmhD0ZDwmuk8GN+qc0YRNOzzJ/2UbHH9L/lvGqui8I6WLOi8nDAkEA9CYq
ewfdZ9LcytGz7QwPEeWVhvpm0HQV9moetFWVolYecqBP4QzNyokVnpeUOqhIQAwe
Z0FJEQ9VWsG+Df0noQJBALFjUUZEtv4x31gMlV24oiSWHxIRX4fEND/6LpjleDZ5
C/tY+lZIEO1Gg/FxSMB+hwwhwfSuE3WohZfEcSy+R48=
-----END RSA PRIVATE KEY-----"""

gcp_config = {
  "google_credentials_location": "/home/thiagorramos/Downloads/codecov-311a0005573e.json"
}


class TestGCPStorateService(BaseTestCase):

    def test_create_bucket(self, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        bucket_name = 'thiagoarchivetest'
        res = storage.create_root_storage(bucket_name)
        assert res.name == 'thiagoarchivetest'

    def test_create_bucket_already_exists(self, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        bucket_name = 'testingarchive'
        with pytest.raises(BucketAlreadyExistsError):
            storage.create_root_storage(bucket_name)

    def test_write_then_read_file(self, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        path = 'test_write_then_read_file/result'
        data = 'lorem ipsum dolor test_write_then_read_file á'
        bucket_name = 'testingarchive'
        writing_result = storage.write_file(bucket_name, path, data)
        assert writing_result
        reading_result = storage.read_file(bucket_name, path)
        assert reading_result.decode() == data

    def test_write_then_append_then_read_file(self, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        path = 'test_write_then_append_then_read_file/result'
        data = 'lorem ipsum dolor test_write_then_read_file á'
        second_data = 'mom, look at me, appending data'
        bucket_name = 'testingarchive'
        writing_result = storage.write_file(bucket_name, path, data)
        second_writing_result = storage.append_to_file(bucket_name, path, second_data)
        assert writing_result
        assert second_writing_result
        reading_result = storage.read_file(bucket_name, path)
        assert reading_result.decode() == '\n'.join([data, second_data])

    def test_read_file_does_not_exist(self, request, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        path = f'{request.node.name}/does_not_exist.txt'
        bucket_name = 'testingarchive'
        with pytest.raises(FileNotInStorageError):
            storage.read_file(bucket_name, path)

    def test_write_then_delete_file(self, request, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        path = f'{request.node.name}/result.txt'
        data = 'lorem ipsum dolor test_write_then_read_file á'
        bucket_name = 'testingarchive'
        writing_result = storage.write_file(bucket_name, path, data)
        assert writing_result
        deletion_result = storage.delete_file(bucket_name, path)
        assert deletion_result is True
        with pytest.raises(FileNotInStorageError):
            storage.read_file(bucket_name, path)

    def test_delete_file_doesnt_exist(self, request, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        path = f'{request.node.name}/result.txt'
        bucket_name = 'testingarchive'
        with pytest.raises(FileNotInStorageError):
            storage.delete_file(bucket_name, path)

    def test_batch_delete_files(self, request, codecov_vcr):
        storage = GCPStorageService(
            gcp_config
        )
        path_1 = f'{request.node.name}/result_1.txt'
        path_2 = f'{request.node.name}/result_2.txt'
        path_3 = f'{request.node.name}/result_3.txt'
        paths = [path_1, path_2, path_3]
        data = 'lorem ipsum dolor test_write_then_read_file á'
        bucket_name = 'testingarchive'
        storage.write_file(bucket_name, path_1, data)
        storage.write_file(bucket_name, path_3, data)
        deletion_result = storage.delete_files(bucket_name, paths)
        assert deletion_result == [True, False, True]
        for p in paths:
            with pytest.raises(FileNotInStorageError):
                storage.read_file(bucket_name, p)
