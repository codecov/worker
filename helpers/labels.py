from enum import Enum

from shared.reports.resources import Report

# The SpecialLabelsEnum enum is place to hold sentinels for labels with special
#     meanings
# One example is CODECOV_ALL_LABELS_PLACEHOLDER: it's a sentinel for
#     "all the labels from this report apply here"
# Imagine a suite, with many tests, that import a particular file
# The imports all happen before any of the tests is executed
# So on this imported file, there might be some global code
# Because it's global, it runs during this import phase
# So it's not attached directly to any test, because it ran
#     outside of any tests
# But it is responsible for those tests in a way, since this global variable
# is used in the functions themselves (which run during the tests). At least
#     there is no simple way to guarantee the global variable didn't affect
#     anything that imported that file
# So, from the coverage perspective, this global-level line was an indirect
#     part of every test. So, in the end, if we see this constant in the report
#     datapoints, we will replace it with all the labels (tests) that we saw in
#     that report
# This is what CODECOV_ALL_LABELS_PLACEHOLDER is


class SpecialLabelsEnum(Enum):
    CODECOV_ALL_LABELS_PLACEHOLDER = ("Th2dMtk4M_codecov", 0)

    def __init__(self, label, index):
        self.corresponding_label = label
        self.corresponding_index = index


def get_labels_per_session(report: Report, sess_id: int) -> set[str | int]:
    """Returns a Set with the labels present in a session from report, EXCLUDING the SpecialLabel.

    The return value can either be a set of strings (the labels themselves) OR
    a set of ints (the label indexes). The label can be looked up from the index
    using Report.lookup_label_by_id(label_id) (assuming Report._labels_idx is set)
    """
    all_labels: set[str | int] = set()

    for file in report:
        for _, line in file.lines:
            if line.datapoints:
                for datapoint in line.datapoints:
                    if datapoint.sessionid == sess_id:
                        all_labels.update(datapoint.label_ids or [])

    return all_labels - {
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index,
    }


def get_all_report_labels(report: Report) -> set[str | int]:
    """Returns a Set with the labels present in report EXCLUDING the SpecialLabel.

    The return value can either be a set of strings (the labels themselves) OR
    a set of ints (the label indexes). The label can be looked up from the index
    using Report.lookup_label_by_id(label_id) (assuming Report._labels_idx is set)
    """
    all_labels: set[str | int] = set()
    for file in report:
        for _, line in file.lines:
            if line.datapoints:
                for datapoint in line.datapoints:
                    all_labels.update(datapoint.label_ids or [])

    return all_labels - {
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label,
        SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_index,
    }
