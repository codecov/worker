from tests.base import BaseTestCase
from services.archive import ArchiveService
from database.tests.factories import RepositoryFactory


class TestArchiveService(BaseTestCase):

    def test_read_file_hard_to_decode(self, mock_storage):
        repo = RepositoryFactory.create()
        service = ArchiveService(repo)
        expected_result = '�abc'
        path = 'path/to/file'
        mock_storage.read_file.return_value = b'\x80abc'
        result = service.read_file(path)
        assert expected_result == result
