from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_json(json, fix, ignored_lines, sessionid):
    report = Report()
    for data in json['files']:
        fn = fix(data['filename'])
        if fn is None:
            continue

        _file = ReportFile(fn, ignore=ignored_lines.get(fn))

        for ln, cov in enumerate(data['coverage'], start=1):
            _file[ln] = ReportLine(coverage=cov,
                                   sessions=[[sessionid, cov]])

        report.append(_file)

    return report
