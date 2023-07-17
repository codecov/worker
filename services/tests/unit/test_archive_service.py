import json

from shared.storage import MinioStorageService

from database.tests.factories import RepositoryFactory
from services.archive import ArchiveService
from test_utils.base import BaseTestCase


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


class TestWriteJsonData(BaseTestCase):
    def test_write_report_details_to_storage(self, mocker, dbsession):
        repo = RepositoryFactory()
        dbsession.add(repo)
        dbsession.flush()
        mock_write_file = mocker.patch.object(MinioStorageService, "write_file")

        data = [
            {
                "filename": "file_1.go",
                "file_index": 0,
                "file_totals": [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0],
                "session_totals": {
                    "0": [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2],
                    "meta": {"session_count": 1},
                },
                "diff_totals": None,
            },
            {
                "filename": "file_2.py",
                "file_index": 1,
                "file_totals": [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                "session_totals": {
                    "0": [0, 2, 1, 0, 1, "50.00000", 1],
                    "meta": {"session_count": 1},
                },
                "diff_totals": None,
            },
        ]
        archive_service = ArchiveService(repository=repo)
        commitid = "some-commit-sha"
        external_id = "some-uuid4-id"
        path = archive_service.write_json_data_to_storage(
            commit_id=commitid,
            table="reports_reportdetails",
            field="files_array",
            external_id=external_id,
            data=data,
        )
        assert (
            path
            == f"v4/repos/{archive_service.storage_hash}/commits/{commitid}/json_data/reports_reportdetails/files_array/{external_id}.json"
        )
        mock_write_file.assert_called_with(
            archive_service.root,
            path,
            json.dumps(data),
            is_already_gzipped=False,
            reduced_redundancy=False,
        )
