from tests.base import BaseTestCase
from services.archive import ArchiveService
from database.tests.factories import RepositoryFactory
from covreports.storage import MinioStorageService


class TestArchiveService(BaseTestCase):
    def test_read_file_hard_to_decode(self, mocker):
        mock_read_file = mocker.patch.object(MinioStorageService, "read_file")
        mock_read_file.return_value = b"\x80abc"
        repo = RepositoryFactory.create()
        service = ArchiveService(repo)
        expected_result = "�abc"
        path = "path/to/file"
        result = service.read_file(path)
        assert expected_result == result
