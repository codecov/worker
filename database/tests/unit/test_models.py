import json
from unittest.mock import PropertyMock, call

from mock import MagicMock, patch
from shared.reports.types import ReportTotals, SessionTotalsArray
from shared.storage.exceptions import FileNotInStorageError
from shared.utils.ReportEncoder import ReportEncoder

from database.models import Branch, Commit, CommitNotification, Owner, Pull, Repository
from database.models.reports import ReportDetails
from database.tests.factories import (
    BranchFactory,
    CommitFactory,
    CommitNotificationFactory,
    CompareCommitFactory,
    OwnerFactory,
    PullFactory,
    RepositoryFactory,
)
from database.tests.factories.core import ReportDetailsFactory


class TestReprModels(object):
    def test_owner_repr(self, dbsession):
        simple_owner = Owner()
        assert "Owner<None@service<None>>" == repr(simple_owner)
        factoried_owner = OwnerFactory.create(service="github")
        assert "Owner<None@service<github>>" == repr(factoried_owner)
        dbsession.add(factoried_owner)
        dbsession.flush()
        dbsession.refresh(factoried_owner)
        assert f"Owner<{factoried_owner.ownerid}@service<github>>" == repr(
            factoried_owner
        )

    def test_repo_repr(self, dbsession):
        simple_repo = Repository()
        assert "Repo<None>" == repr(simple_repo)
        factoried_repo = RepositoryFactory.create()
        assert "Repo<None>" == repr(factoried_repo)
        dbsession.add(factoried_repo)
        dbsession.flush()
        dbsession.refresh(factoried_repo)
        assert f"Repo<{factoried_repo.repoid}>" == repr(factoried_repo)

    def test_commit_repr(self, dbsession):
        simple_commit = Commit()
        assert "Commit<None@repo<None>>" == repr(simple_commit)
        factoried_commit = CommitFactory.create(
            commitid="327993f5d81eda4bac19ea6090fe68c8eb313066"
        )
        assert "Commit<327993f5d81eda4bac19ea6090fe68c8eb313066@repo<None>>" == repr(
            factoried_commit
        )
        dbsession.add(factoried_commit)
        dbsession.flush()
        dbsession.refresh(factoried_commit)
        assert (
            f"Commit<327993f5d81eda4bac19ea6090fe68c8eb313066@repo<{factoried_commit.repoid}>>"
            == repr(factoried_commit)
        )

    def test_branch_repr(self, dbsession):
        simple_branch = Branch()
        assert "Branch<None@repo<None>>" == repr(simple_branch)
        factoried_branch = BranchFactory.create(branch="thisoakbranch")
        assert "Branch<thisoakbranch@repo<None>>" == repr(factoried_branch)
        dbsession.add(factoried_branch)
        dbsession.flush()
        dbsession.refresh(factoried_branch)
        assert f"Branch<thisoakbranch@repo<{factoried_branch.repoid}>>" == repr(
            factoried_branch
        )

    def test_pull_repr(self, dbsession):
        simple_pull = Pull()
        assert "Pull<None@repo<None>>" == repr(simple_pull)
        factoried_pull = PullFactory.create()
        assert f"Pull<{factoried_pull.pullid}@repo<None>>" == repr(factoried_pull)
        dbsession.add(factoried_pull)
        dbsession.flush()
        dbsession.refresh(factoried_pull)
        assert f"Pull<{factoried_pull.pullid}@repo<{factoried_pull.repoid}>>" == repr(
            factoried_pull
        )

    def test_notification_repr(self, dbsession):
        simple_notification = CommitNotification()
        assert "Notification<None@commit<None>>" == repr(simple_notification)
        factoried_notification = CommitNotificationFactory.create()
        assert (
            f"Notification<{factoried_notification.notification_type}@commit<{factoried_notification.commit_id}>>"
            == repr(factoried_notification)
        )
        dbsession.add(factoried_notification)
        dbsession.flush()
        dbsession.refresh(factoried_notification)
        assert (
            f"Notification<{factoried_notification.notification_type}@commit<{factoried_notification.commit_id}>>"
            == repr(factoried_notification)
        )

    def test_commit_compare_repr(self, dbsession):
        compare_commit = CompareCommitFactory()
        assert "CompareCommit<None...None>" == repr(compare_commit)

    def test_commit_notified(self, dbsession):
        commit = CommitFactory.create()
        dbsession.add(commit)
        dbsession.flush()
        assert commit.notified is None
        commit.notified = True
        dbsession.flush()
        dbsession.refresh(commit)
        assert commit.notified is True


class TestPullModel(object):
    def test_updatestamp_update(self, dbsession):
        factoried_pull = PullFactory.create(updatestamp=None)
        assert factoried_pull.updatestamp is None
        dbsession.add(factoried_pull)
        dbsession.flush()
        assert factoried_pull.updatestamp is not None
        val = factoried_pull.updatestamp
        factoried_pull.title = "Super Mario Bros"
        dbsession.flush()
        assert factoried_pull.updatestamp is not None
        assert factoried_pull.updatestamp > val


class TestReportDetailsModel(object):

    sample_files_array = [
        {
            "filename": "file_1.go",
            "file_index": 0,
            "file_totals": ReportTotals(
                *[0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0]
            ),
            "session_totals": SessionTotalsArray.build_from_encoded_data(
                {
                    "0": [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2],
                    "meta": {"session_count": 1},
                }
            ),
            "diff_totals": None,
        },
        {
            "filename": "file_2.py",
            "file_index": 1,
            "file_totals": ReportTotals(
                *[0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0]
            ),
            "session_totals": SessionTotalsArray.build_from_encoded_data(
                {
                    "0": [0, 2, 1, 0, 1, "50.00000", 1],
                    "meta": {"session_count": 1},
                }
            ),
            "diff_totals": None,
        },
    ]

    def test_rehydrate_already_hydrated(self):
        fully_encoded_sample = [
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
        half_encoded_sample = [
            {
                "filename": "file_1.go",
                "file_index": 0,
                "file_totals": ReportTotals(
                    *[0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0]
                ),
                "session_totals": {
                    "0": [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2],
                    "meta": {"session_count": 1},
                },
                "diff_totals": None,
            },
            {
                "filename": "file_2.py",
                "file_index": 1,
                "file_totals": ReportTotals(
                    *[0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0]
                ),
                "session_totals": {
                    "0": [0, 2, 1, 0, 1, "50.00000", 1],
                    "meta": {"session_count": 1},
                },
                "diff_totals": None,
            },
        ]
        rd: ReportDetails = ReportDetailsFactory()
        assert (
            rd.rehydrate_encoded_data(self.sample_files_array)
            == self.sample_files_array
        )
        assert (
            rd.rehydrate_encoded_data(fully_encoded_sample) == self.sample_files_array
        )
        assert rd.rehydrate_encoded_data(half_encoded_sample) == self.sample_files_array

    def test_get_files_array_from_db(self, dbsession, mocker):
        factory_report_details: ReportDetails = ReportDetailsFactory()
        factory_report_details._files_array = self.sample_files_array
        factory_report_details._files_array_storage_path = None
        dbsession.add(factory_report_details)
        dbsession.flush()

        mock_archive_service = mocker.patch("database.utils.ArchiveService")
        retrieved_instance = dbsession.query(ReportDetails).get(
            factory_report_details.id_
        )
        assert retrieved_instance.external_id == factory_report_details.external_id
        files_array = retrieved_instance.files_array
        assert files_array == self.sample_files_array
        mock_archive_service.assert_not_called()

    def test_get_files_array_from_storage(self, dbsession, mocker):
        factory_report_details: ReportDetails = ReportDetailsFactory()
        factory_report_details._files_array = None
        factory_report_details._files_array_storage_path = (
            "https://storage-url/path/to/item.json"
        )
        dbsession.add(factory_report_details)
        dbsession.flush()

        mock_archive_service = mocker.patch("database.utils.ArchiveService")
        mock_archive_service.return_value.read_file.return_value = json.dumps(
            self.sample_files_array, cls=ReportEncoder
        )
        retrieved_instance = dbsession.query(ReportDetails).get(
            factory_report_details.id_
        )
        assert retrieved_instance.external_id == factory_report_details.external_id
        files_array = retrieved_instance.files_array
        assert files_array == self.sample_files_array
        assert mock_archive_service.call_count == 1
        mock_archive_service.return_value.read_file.assert_has_calls(
            [call("https://storage-url/path/to/item.json")]
        )
        # Check that caching works within the instance
        files_array = retrieved_instance.files_array
        assert mock_archive_service.call_count == 1
        assert mock_archive_service.return_value.read_file.call_count == 1

    def test_get_files_array_from_storage_error(self, dbsession, mocker):
        factory_report_details: ReportDetails = ReportDetailsFactory()
        factory_report_details._files_array = None
        factory_report_details._files_array_storage_path = (
            "https://storage-url/path/to/item.json"
        )
        dbsession.add(factory_report_details)
        dbsession.flush()

        mocker.patch(
            "database.utils.ArchiveField.read_timeout",
            new_callable=PropertyMock,
            return_value=0.1,
        )
        mock_archive_service = mocker.patch("database.utils.ArchiveService")

        def side_effect(path):
            assert path == "https://storage-url/path/to/item.json"
            raise FileNotInStorageError()

        mock_archive_service.return_value.read_file.side_effect = side_effect
        retrieved_instance = dbsession.query(ReportDetails).get(
            factory_report_details.id_
        )
        files_array = retrieved_instance.files_array
        assert files_array == []
        assert mock_archive_service.call_count == 1
        mock_archive_service.return_value.read_file.assert_has_calls(
            [call("https://storage-url/path/to/item.json")]
        )

    def test__should_write_to_storage(self, dbsession, mocker, mock_configuration):
        factory_report_details: ReportDetails = ReportDetailsFactory()
        codecov_report_details: ReportDetails = ReportDetailsFactory(
            report__commit__repository__owner__username="codecov"
        )
        allowlisted_repo: ReportDetails = ReportDetailsFactory()
        dbsession.add(factory_report_details)
        dbsession.add(codecov_report_details)
        dbsession.add(allowlisted_repo)
        dbsession.flush()

        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "repo_ids": [allowlisted_repo.report.commit.repository.repoid],
                        "report_details_files_array": "restricted_access",
                    },
                }
            }
        )
        assert factory_report_details._should_write_to_storage() == False
        assert allowlisted_repo._should_write_to_storage() == True
        assert codecov_report_details._should_write_to_storage() == True
        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "repo_ids": [],
                        "report_details_files_array": False,
                    },
                }
            }
        )
        assert factory_report_details._should_write_to_storage() == False
        assert allowlisted_repo._should_write_to_storage() == False
        assert codecov_report_details._should_write_to_storage() == False

    def test_set_files_array_to_db(self, dbsession, mocker, mock_configuration):
        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "only_codecov": False,
                        "report_details_files_array": False,
                    },
                }
            }
        )
        mock_archive_service = mocker.patch("database.utils.ArchiveService")

        factory_report_details: ReportDetails = ReportDetailsFactory()
        # Setting files_array.
        factory_report_details.files_array = self.sample_files_array
        dbsession.add(factory_report_details)
        dbsession.flush()

        retrieved_instance = dbsession.query(ReportDetails).get(
            factory_report_details.id_
        )
        assert retrieved_instance.external_id == factory_report_details.external_id
        files_array = retrieved_instance.files_array
        assert files_array == self.sample_files_array
        mock_archive_service.assert_not_called()

    def test_set_files_array_to_storage(self, dbsession, mocker, mock_configuration):
        mock_configuration.set_params(
            {
                "setup": {
                    "save_report_data_in_storage": {
                        "report_details_files_array": "general_access",
                    },
                }
            }
        )
        mock_archive_service = mocker.patch("database.utils.ArchiveService")
        mock_archive_service.return_value.read_file.return_value = json.dumps(
            self.sample_files_array, cls=ReportEncoder
        )
        mock_archive_service.return_value.write_json_data_to_storage.return_value = (
            "https://storage-url/path/to/item.json"
        )

        factory_report_details: ReportDetails = ReportDetailsFactory()
        dbsession.add(factory_report_details)
        dbsession.flush()

        retrieved_instance = dbsession.query(ReportDetails).get(
            factory_report_details.id_
        )
        # The default value from factory is []
        assert retrieved_instance.files_array == []
        assert mock_archive_service.call_count == 0
        assert mock_archive_service.return_value.read_file.call_count == 0
        # Set the new value
        retrieved_instance.files_array = self.sample_files_array
        assert mock_archive_service.call_count == 1
        mock_archive_service.return_value.write_json_data_to_storage.assert_has_calls(
            [
                call(
                    commit_id=retrieved_instance.report.commit.commitid,
                    table="reports_reportdetails",
                    field="files_array",
                    external_id=retrieved_instance.external_id,
                    data=self.sample_files_array,
                    encoder=ReportEncoder,
                )
            ]
        )
        # Retrieve the set value
        files_array = retrieved_instance.files_array
        assert files_array == self.sample_files_array
        assert mock_archive_service.call_count == 1
        # Check that caching works within the instance
        files_array = retrieved_instance.files_array
        assert mock_archive_service.call_count == 1
        assert mock_archive_service.return_value.read_file.call_count == 0


class TestCommitModel(object):
    sample_report = {
        "files": {
            "different/test_file.py": [
                2,
                [0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0],
                [[0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0]],
                [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            ],
        },
        "sessions": {
            "0": {
                "N": None,
                "a": "v4/raw/2019-01-10/4434BC2A2EC4FCA57F77B473D83F928C/abf6d4df662c47e32460020ab14abf9303581429/9ccc55a1-8b41-4bb1-a946-ee7a33a7fb56.txt",
                "c": None,
                "d": 1547084427,
                "e": None,
                "f": ["unittests"],
                "j": None,
                "n": None,
                "p": None,
                "t": [3, 20, 17, 3, 0, "85.00000", 0, 0, 0, 0, 0, 0, 0],
                "": None,
            }
        },
    }

    @patch("database.utils.ArchiveService")
    def test_get_report_from_db(self, mock_archive, dbsession):
        commit = CommitFactory()
        mock_read_file = MagicMock()
        mock_archive.return_value.read_file = mock_read_file
        commit._report_json = self.sample_report
        dbsession.add(commit)
        dbsession.flush()

        fetched = dbsession.query(Commit).get(commit.id_)
        assert fetched.report_json == self.sample_report
        mock_archive.assert_not_called()
        mock_read_file.assert_not_called()

    @patch("database.utils.ArchiveService")
    def test_get_report_from_storage(self, mock_archive, dbsession):
        commit = CommitFactory()
        storage_path = "https://storage/path/report.json"
        mock_read_file = MagicMock(return_value=json.dumps(self.sample_report))
        mock_archive.return_value.read_file = mock_read_file
        commit._report_json = None
        commit._report_json_storage_path = storage_path
        dbsession.add(commit)
        dbsession.flush()

        fetched = dbsession.query(Commit).get(commit.id_)
        assert fetched.report_json == self.sample_report
        mock_archive.assert_called()
        mock_read_file.assert_called_with(storage_path)
        # Calls it again to test caching
        assert fetched.report_json == self.sample_report
        assert mock_archive.call_count == 1
        assert mock_read_file.call_count == 1
        # This one to help us understand caching across different instances
        # different instances if they are the same
        assert commit.report_json == self.sample_report
        assert mock_archive.call_count == 1
        assert mock_read_file.call_count == 1
        # Let's see for objects with different IDs
        diff_commit = CommitFactory()
        storage_path = "https://storage/path/files_array.json"
        diff_commit._report_json = None
        diff_commit._report_json_storage_path = storage_path
        dbsession.add(diff_commit)
        dbsession.flush()
        assert diff_commit.report_json == self.sample_report
        assert mock_archive.call_count == 2
        assert mock_read_file.call_count == 2

    @patch("database.utils.ArchiveService")
    def test_get_report_from_storage_file_not_found(
        self, mock_archive, dbsession, mocker
    ):
        mocker.patch(
            "database.utils.ArchiveField.read_timeout",
            new_callable=PropertyMock,
            return_value=0.1,
        )
        commit = CommitFactory()
        storage_path = "https://storage/path/files_array.json"

        def side_effect(*args, **kwargs):
            raise FileNotInStorageError()

        mock_read_file = MagicMock(side_effect=side_effect)
        mock_archive.return_value.read_file = mock_read_file
        commit._report_json = None
        commit._report_json_storage_path = storage_path
        dbsession.add(commit)
        dbsession.flush()

        fetched = dbsession.query(Commit).get(commit.id_)
        assert fetched._report_json_storage_path == storage_path
        assert fetched.report_json == {}
        mock_archive.assert_called()
        mock_read_file.assert_called_with(storage_path)
