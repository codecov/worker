import hashlib
import json

import pytest
from shared.reports.resources import Report

from database.tests.factories.core import ReportFactory
from helpers.labels import SpecialLabelsEnum
from services.report.labels_index import ArchiveService, LabelsIndexService


class TestLabelsIndex(object):
    def test_init(self, dbsession, mocker):
        commit_report = ReportFactory()
        dbsession.add(commit_report)
        dbsession.flush()

        labels_index_service = LabelsIndexService.from_commit_report(commit_report)
        assert labels_index_service._archive_client is not None
        assert labels_index_service.commit_sha == commit_report.commit.commitid

    def test_set_label_idx(self, dbsession, mocker):
        commit_report = ReportFactory()
        dbsession.add(commit_report)
        dbsession.flush()
        # Notice that the keys are strings
        # because self._archive_client.read_label_index returns the contents of a JSON file,
        # and JSON can only have string keys.
        sample_label_index = {
            "0": SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            "1": "some_label",
            "2": "another_label",
        }
        mocker.patch.object(
            ArchiveService, "read_label_index", return_value=sample_label_index
        )
        report = Report()
        assert report.labels_index == None
        label_service = LabelsIndexService.from_commit_report(commit_report)
        label_service.set_label_idx(report)
        assert report.labels_index == {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "some_label",
            2: "another_label",
        }

    def test_set_label_idx_already_set(self, dbsession, mocker):
        commit_report = ReportFactory()
        dbsession.add(commit_report)
        dbsession.flush()
        mock_read = mocker.patch.object(ArchiveService, "read_label_index")
        sample_label_index = {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "some_label",
            2: "another_label",
        }
        report = Report()
        report.labels_index = sample_label_index
        with pytest.raises(Exception) as exp:
            label_service = LabelsIndexService.from_commit_report(commit_report)
            label_service.set_label_idx(report)
        mock_read.assert_not_called()
        assert (
            str(exp.value)
            == "Trying to set labels_index of Report, but it's already set"
        )

    def test_unset_label_idx(self, dbsession, mocker):
        commit_report = ReportFactory()
        dbsession.add(commit_report)
        dbsession.flush()
        sample_label_index = {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "some_label",
            2: "another_label",
        }
        mock_write = mocker.patch.object(ArchiveService, "write_label_index")
        report = Report()
        report.labels_index = sample_label_index
        label_service = LabelsIndexService.from_commit_report(commit_report)
        label_service.save_and_unset_label_idx(report)
        assert report.labels_index == None
        mock_write.assert_called_with(
            commit_report.commit.commitid, sample_label_index, commit_report.code
        )

    def test_load_then_unload_no_change(self, dbsession, mock_storage, mocker):
        commit_report = ReportFactory()
        report = Report()
        dbsession.add(commit_report)
        dbsession.flush()
        sample_label_index = {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "some_label",
            2: "another_label",
        }
        archive_hash = ArchiveService.get_archive_hash(commit_report.commit.repository)
        labels_index_path = f"v4/repos/{archive_hash}/commits/{commit_report.commit.commitid}/labels_index.json"
        mock_storage.write_file(
            "archive", labels_index_path, json.dumps(sample_label_index)
        )
        mock_archive_service = mocker.patch.object(ArchiveService, "write_label_index")

        label_service = LabelsIndexService.from_commit_report(commit_report)
        assert label_service.loaded_hash is None
        label_service.set_label_idx(report)
        assert (
            label_service.loaded_hash
            == hashlib.sha1(json.dumps(sample_label_index).encode()).hexdigest()
        )
        # Unset the index with no change should not trigger a re-write to storage
        label_service.save_and_unset_label_idx(report)
        mock_archive_service.assert_not_called()
        assert report.labels_index is None
        # Clean up by removign the saved file
        # To avoid issues with other tests
        mock_storage.delete_file("archive", labels_index_path)

    def test_load_then_unload_with_change(self, dbsession, mock_storage, mocker):
        commit_report = ReportFactory()
        report = Report()
        dbsession.add(commit_report)
        dbsession.flush()
        sample_label_index = {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "some_label",
            2: "another_label",
        }
        archive_hash = ArchiveService.get_archive_hash(commit_report.commit.repository)
        labels_index_path = f"v4/repos/{archive_hash}/commits/{commit_report.commit.commitid}/labels_index.json"
        mock_storage.write_file(
            "archive", labels_index_path, json.dumps(sample_label_index)
        )
        mock_archive_service = mocker.patch.object(ArchiveService, "write_label_index")

        label_service = LabelsIndexService.from_commit_report(commit_report)
        assert label_service.loaded_hash is None
        label_service.set_label_idx(report)
        assert (
            label_service.loaded_hash
            == hashlib.sha1(json.dumps(sample_label_index).encode()).hexdigest()
        )

        report.labels_index[3] = "a_wild_label_appears"
        # Unset the index with change should trigger a re-write to storage
        label_service.save_and_unset_label_idx(report)
        mock_archive_service.assert_called()
        assert report.labels_index is None
        # Clean up by removign the saved file
        # To avoid issues with other tests
        mock_storage.delete_file("archive", labels_index_path)
