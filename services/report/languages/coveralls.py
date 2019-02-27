from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def detect(report):
    return 'source_files' in report


def from_json(report, fix, ignored_lines, sessionid):
    # https://github.com/codecov/support/issues/253
    _report = Report()
    for _file in report['source_files']:
        filename = fix(_file['name'])
        if filename:
            report_file = ReportFile(filename,
                                     ignore=ignored_lines.get(filename))
            for ln, coverage in enumerate(_file['coverage'], start=1):
                if coverage is not None:
                    report_file[ln] = ReportLine(coverage, None, [[sessionid, coverage]])
            _report.append(report_file)

    return _report
