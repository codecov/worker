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
                "diff_totals": None,
            },
            {
                "filename": "file_2.py",
                "file_index": 1,
                "file_totals": [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
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

    def test_write_report_details_to_storage_no_commitid(self, mocker, dbsession):
        repo = RepositoryFactory()
        dbsession.add(repo)
        dbsession.flush()
        mock_write_file = mocker.patch.object(MinioStorageService, "write_file")

        data = [
            {
                "filename": "file_1.go",
                "file_index": 0,
                "file_totals": [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0],
                "diff_totals": None,
            },
            {
                "filename": "file_2.py",
                "file_index": 1,
                "file_totals": [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                "diff_totals": None,
            },
        ]
        archive_service = ArchiveService(repository=repo)
        commitid = None
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
            == f"v4/repos/{archive_service.storage_hash}/json_data/reports_reportdetails/files_array/{external_id}.json"
        )
        mock_write_file.assert_called_with(
            archive_service.root,
            path,
            json.dumps(data),
            is_already_gzipped=False,
            reduced_redundancy=False,
        )
