from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_json(json, fix, ignored_lines, sessionid):
    report = Report()
    for fn, data in json['files'].iteritems():
        fn = fix(fn)
        if fn is None:
            continue

        _file = ReportFile(fn, ignore=ignored_lines.get(fn))

        for loc in data['expressions'].get('covered_locs', []):
            start, end = loc['start'], loc['end']
            partials = [[start['column'], end['column'], 1]] if start['line'] == end['line'] else None
            _file[start['line']] = ReportLine(coverage=1,
                                              sessions=[[sessionid, 1, None, partials]])

        for loc in data['expressions'].get('uncovered_locs', []):
            start, end = loc['start'], loc['end']
            partials = [[start['column'], end['column'], 0]] if start['line'] == end['line'] else None
            _file[start['line']] = ReportLine(coverage=0,
                                              sessions=[[sessionid, 0, None, partials]])

        report.append(_file)

    return report
