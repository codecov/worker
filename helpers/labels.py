from enum import Enum

import sentry_sdk
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
    CODECOV_ALL_LABELS_PLACEHOLDER = "Th2dMtk4M_codecov"

    def __init__(self, val):
        self.corresponding_label = val


@sentry_sdk.trace
def get_labels_per_session(report: Report, sess_id: int):
    all_labels = set()
    for rf in report:
        for _, line in rf.lines:
            if line.datapoints:
                for datapoint in line.datapoints:
                    if datapoint.sessionid == sess_id:
                        all_labels.update(datapoint.labels or [])
    return all_labels - set(
        [SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label]
    )


@sentry_sdk.trace
def get_all_report_labels(report: Report) -> set:
    all_labels = set()
    for rf in report:
        for _, line in rf.lines:
            if line.datapoints:
                for datapoint in line.datapoints:
                    all_labels.update(datapoint.labels or [])
    return all_labels - set(
        [SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER.corresponding_label]
    )
