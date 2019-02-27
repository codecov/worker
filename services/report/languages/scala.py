from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_json(data_dict, fix, ignored_lines, sessionid):
    report = Report()
    for f in data_dict['fileReports']:
        filename = fix(f['filename'])
        if filename is None:
            continue
        _file = ReportFile(filename, ignore=ignored_lines.get(filename))
        fs = _file.__setitem__
        [fs(int(ln), ReportLine(cov, None, [[sessionid, cov]])) for ln, cov in f['coverage'].iteritems()]
        report.append(_file)
    return report
