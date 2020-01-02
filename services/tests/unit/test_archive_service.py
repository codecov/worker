from tests.base import BaseTestCase
from services.archive import ArchiveService
from database.tests.factories import RepositoryFactory


class TestArchiveService(BaseTestCase):

    def test_read_file_hard_to_decode(self):
        repo = RepositoryFactory.create()
        service = ArchiveService(repo)
        expected_result = '�abc'
        path = 'path/to/file'
        result = service.read_file(path)
        assert expected_result == result
