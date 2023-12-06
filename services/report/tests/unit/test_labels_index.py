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

        labels_index_service = LabelsIndexService(commit_report)
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
        # TODO: Needs shared update
        # assert report._labels_index == None
        label_service = LabelsIndexService(commit_report)
        res = label_service.set_label_idx(report)
        assert res == {
            0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
            1: "some_label",
            2: "another_label",
        }

    # TODO: Needs shared update
    # def test_set_label_idx_already_set(self, dbsession, mocker):
    #     commit_report = ReportFactory()
    #     dbsession.add(commit_report)
    #     dbsession.flush()
    #     mock_read = mocker.patch.object(ArchiveService, "read_label_index")
    #     sample_label_index = {
    #         0: SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
    #         1: "some_label",
    #         2: "another_label",
    #     }
    #     report = Report()
    #     report._labels_index = sample_label_index
    #     with pytest.raises(Exception) as exp:
    #         label_service = LabelsIndexService(commit_report)
    #         label_service.set_label_idx(report)
    #     mock_read.assert_not_called()
    #     assert (
    #         str(exp.value)
    #         == "Trying to set labels_index of Report, but it's already set"
    #     )

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
        # TODO: Needs shared update
        # report._labels_index = sample_label_index
        label_service = LabelsIndexService(commit_report)
        label_service.unset_label_idx(report, sample_label_index)
        # assert report._labels_index == None
        mock_write.assert_called_with(
            commit_report.commit.commitid, sample_label_index, commit_report.code
        )
