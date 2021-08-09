from tests.base import BaseTestCase
from services.archive import ArchiveService
from database.tests.factories import RepositoryFactory
from shared.storage import MinioStorageService


class TestArchiveService(BaseTestCase):
    def test_read_file_hard_to_decode(self, mocker):
        mock_read_file = mocker.patch.object(MinioStorageService, "read_file")
        mock_read_file.return_value = b"\x80abc"
        repo = RepositoryFactory.create()
        service = ArchiveService(repo)
        expected_result = b"\x80abc"
        path = "path/to/file"
        result = service.read_file(path)
        assert expected_result == result

    def test_delete_repo_files(self, mocker):
        mock_delete_files = mocker.patch.object(MinioStorageService, "delete_files")
        mock_delete_files.return_value = [True, True]

        mock_list_folder_contents = mocker.patch.object(
            MinioStorageService, "list_folder_contents"
        )
        mock_list_folder_contents.return_value = [
            {"name": "file1", "size": 84},
            {"name": "freedom.txt", "size": 84},
        ]

        repo = RepositoryFactory.create()
        service = ArchiveService(repo)
        result = service.delete_repo_files()
        assert result == 2
