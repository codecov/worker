from shared.reports.resources import LineSession, ReportFile, ReportLine

from services.report.report_builder import CoverageType, ReportBuilder


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
    assert builder_session.path_fixer == path_fixer


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
        ReportLine.create(coverage=0),
    )
    first_file.append(
        10,
        ReportLine.create(
            coverage=1,
            sessions=[
                (
                    LineSession(
                        id=0,
                        coverage=1,
                    )
                )
            ],
        ),
    )
    builder_session.append(first_file)
    final_report = builder_session.output_report()
    assert final_report.files == ["filename.py"]
    assert sorted(final_report.get("filename.py").lines) == [
        (
            2,
            ReportLine.create(coverage=0),
        ),
        (
            3,
            ReportLine.create(coverage=0),
        ),
        (
            10,
            ReportLine.create(coverage=1, sessions=[LineSession(id=0, coverage=1)]),
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
        ReportLine.create(coverage=0),
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
        ),
    )
    builder_session.append(first_file)
    final_report = builder_session.output_report()
    assert final_report.files == ["filename.py"]
    assert sorted(final_report.get("filename.py").lines) == [
        (
            2,
            ReportLine.create(coverage=0),
        ),
        (
            3,
            ReportLine.create(coverage=0),
        ),
        (
            10,
            ReportLine.create(
                coverage=1,
                sessions=[LineSession(id=0, coverage=1)],
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
    )
    assert line == ReportLine.create(
        coverage=1,
        type="b",
        sessions=[
            LineSession(
                id=45, coverage=1, branches=None, partials=None, complexity=None
            )
        ],
    )
