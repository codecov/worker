import pytest
from shared.reports.resources import LineSession, ReportFile, ReportLine
from shared.reports.types import CoverageDatapoint

from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    SpecialLabelsEnum,
)


def test_report_builder_generate_session(mocker):
    current_yaml, sessionid, ignored_lines, path_fixer = (
        mocker.MagicMock(),
        mocker.MagicMock(),
        mocker.MagicMock(),
        mocker.MagicMock(),
    )
    filepath = "filepath"
    builder = ReportBuilder(current_yaml, sessionid, ignored_lines, path_fixer)
    builder_session = builder.create_report_builder_session(filepath)
    assert builder_session.file_class == ReportFile
    assert builder_session.path_fixer == path_fixer
    assert builder_session.sessionid == sessionid
    assert builder_session.current_yaml == current_yaml
    assert builder_session.ignored_lines == ignored_lines


def test_report_builder_session(mocker):
    current_yaml, sessionid, ignored_lines, path_fixer = (
        {"beta_groups": ["labels"]},
        mocker.MagicMock(),
        mocker.MagicMock(),
        mocker.MagicMock(),
    )
    filepath = "filepath"
    builder = ReportBuilder(current_yaml, sessionid, ignored_lines, path_fixer)
    builder_session = builder.create_report_builder_session(filepath)
    first_file = ReportFile("filename.py")
    first_file.append(2, ReportLine.create(coverage=0))
    first_file.append(
        3,
        ReportLine.create(
            coverage=0,
            datapoints=[
                CoverageDatapoint(
                    sessionid=0,
                    coverage=1,
                    coverage_type=None,
                    label_ids=[SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER],
                )
            ],
        ),
    )
    first_file.append(
        10,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=0,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=0,
                    coverage=1,
                    coverage_type=None,
                    label_ids=["some_label", "other"],
                ),
                CoverageDatapoint(
                    sessionid=0,
                    coverage=1,
                    coverage_type=None,
                    label_ids=None,
                ),
            ],
            complexity=None,
        ),
    )
    builder_session.append(first_file)
    final_report = builder_session.output_report()
    assert final_report.files == ["filename.py"]
    assert sorted(final_report.get("filename.py").lines) == [
        (
            2,
            ReportLine.create(
                coverage=0, type=None, sessions=None, datapoints=None, complexity=None
            ),
        ),
        (
            3,
            ReportLine.create(
                coverage=0,
                type=None,
                sessions=None,
                datapoints=[
                    CoverageDatapoint(
                        sessionid=0,
                        coverage=1,
                        coverage_type=None,
                        label_ids=["Th2dMtk4M_codecov"],
                    ),
                ],
                complexity=None,
            ),
        ),
        (
            10,
            ReportLine.create(
                coverage=1,
                type=None,
                sessions=[
                    LineSession(
                        id=0, coverage=1, branches=None, partials=None, complexity=None
                    )
                ],
                datapoints=[
                    CoverageDatapoint(
                        sessionid=0,
                        coverage=1,
                        coverage_type=None,
                        label_ids=["some_label", "other"],
                    ),
                    CoverageDatapoint(
                        sessionid=0,
                        coverage=1,
                        coverage_type=None,
                        label_ids=None,
                    ),
                ],
                complexity=None,
            ),
        ),
    ]


def test_report_builder_session_only_all_labels(mocker):
    current_yaml, sessionid, ignored_lines, path_fixer = (
        {},
        mocker.MagicMock(),
        mocker.MagicMock(),
        mocker.MagicMock(),
    )
    filepath = "filepath"
    builder = ReportBuilder(current_yaml, sessionid, ignored_lines, path_fixer)
    builder_session = builder.create_report_builder_session(filepath)
    first_file = ReportFile("filename.py")
    first_file.append(2, ReportLine.create(coverage=0))
    first_file.append(
        3,
        ReportLine.create(
            coverage=0,
            datapoints=[
                CoverageDatapoint(
                    sessionid=0,
                    coverage=1,
                    coverage_type=None,
                    label_ids=[SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER],
                )
            ],
        ),
    )
    first_file.append(
        10,
        ReportLine.create(
            coverage=1,
            type=None,
            sessions=[
                (
                    LineSession(
                        id=0,
                        coverage=1,
                    )
                )
            ],
            datapoints=[
                CoverageDatapoint(
                    sessionid=0,
                    coverage=1,
                    coverage_type=None,
                    label_ids=[SpecialLabelsEnum.CODECOV_ALL_LABELS_PLACEHOLDER],
                ),
                CoverageDatapoint(
                    sessionid=0,
                    coverage=1,
                    coverage_type=None,
                    label_ids=None,
                ),
            ],
            complexity=None,
        ),
    )
    builder_session.append(first_file)
    final_report = builder_session.output_report()
    assert final_report.files == ["filename.py"]
    assert sorted(final_report.get("filename.py").lines) == [
        (
            2,
            ReportLine.create(
                coverage=0, type=None, sessions=None, datapoints=None, complexity=None
            ),
        ),
        (
            3,
            ReportLine.create(
                coverage=0,
                type=None,
                sessions=None,
                datapoints=[
                    CoverageDatapoint(
                        sessionid=0,
                        coverage=1,
                        coverage_type=None,
                        label_ids=["Th2dMtk4M_codecov"],
                    ),
                ],
                complexity=None,
            ),
        ),
        (
            10,
            ReportLine.create(
                coverage=1,
                type=None,
                sessions=[
                    LineSession(
                        id=0, coverage=1, branches=None, partials=None, complexity=None
                    )
                ],
                datapoints=[
                    CoverageDatapoint(
                        sessionid=0,
                        coverage=1,
                        coverage_type=None,
                        label_ids=["Th2dMtk4M_codecov"],
                    ),
                    CoverageDatapoint(
                        sessionid=0,
                        coverage=1,
                        coverage_type=None,
                        label_ids=None,
                    ),
                ],
                complexity=None,
            ),
        ),
    ]


def test_report_builder_session_create_line(mocker):
    current_yaml, sessionid, ignored_lines, path_fixer = (
        {
            "flag_management": {
                "default_rules": {
                    "carryforward": "true",
                    "carryforward_mode": "labels",
                }
            }
        },
        45,
        mocker.MagicMock(),
        mocker.MagicMock(),
    )
    filepath = "filepath"
    builder = ReportBuilder(current_yaml, sessionid, ignored_lines, path_fixer)
    builder_session = builder.create_report_builder_session(filepath)
    line = builder_session.create_coverage_line(1, CoverageType.branch)
    assert line == ReportLine.create(
        coverage=1,
        type="b",
        sessions=[
            LineSession(
                id=45, coverage=1, branches=None, partials=None, complexity=None
            )
        ],
        datapoints=[],
        complexity=None,
    )


def test_report_builder_session_create_line_mixed_labels(mocker):
    current_yaml, sessionid, ignored_lines, path_fixer = (
        {
            "flag_management": {
                "default_rules": {
                    "carryforward": "true",
                    "carryforward_mode": "labels",
                }
            }
        },
        45,
        mocker.MagicMock(),
        mocker.MagicMock(),
    )
    filepath = "filepath"
    builder = ReportBuilder(current_yaml, sessionid, ignored_lines, path_fixer)
    builder_session = builder.create_report_builder_session(filepath)
    line = builder_session.create_coverage_line(
        1,
        CoverageType.branch,
        labels_list_of_lists=[["label1"], [], ["label2"], None],
    )
    assert line == ReportLine.create(
        coverage=1,
        type="b",
        sessions=[
            LineSession(
                id=45, coverage=1, branches=None, partials=None, complexity=None
            )
        ],
        datapoints=[
            CoverageDatapoint(
                sessionid=45,
                coverage=1,
                coverage_type="b",
                label_ids=["label1"],
            ),
            CoverageDatapoint(
                sessionid=45,
                coverage=1,
                coverage_type="b",
                label_ids=["label2"],
            ),
        ],
        complexity=None,
    )


@pytest.mark.parametrize(
    "current_yaml,expected_result",
    [
        ({}, False),
        ({"flags": {"oldflag": {"carryforward": "true"}}}, False),
        (
            {
                "flags": {
                    "oldflag": {"carryforward": "true", "carryforward_mode": "labels"}
                }
            },
            True,
        ),
        (
            {
                "flag_management": {
                    "default_rules": {
                        "carryforward": "true",
                        "carryforward_mode": "labels",
                    }
                }
            },
            True,
        ),
        (
            {
                "flag_management": {
                    "default_rules": {
                        "carryforward": "true",
                        "carryforward_mode": "all",
                    }
                }
            },
            False,
        ),
        (
            {
                "flag_management": {
                    "default_rules": {
                        "carryforward": "true",
                        "carryforward_mode": "all",
                    },
                    "individual_flags": [
                        {
                            "name": "some_flag",
                            "carryforward_mode": "labels",
                        }
                    ],
                }
            },
            True,
        ),
    ],
)
def test_report_builder_supports_flags(current_yaml, expected_result):
    builder = ReportBuilder(current_yaml, 0, None, None)
    assert builder.supports_labels() == expected_result
