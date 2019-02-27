from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_json(json, fix, ignored_lines, sessionid):
    report = Report()
    for obj in json:
        if obj.get('name') and obj.get('lines'):
            fn = fix(obj['name'] + ('.cls' if '.' not in obj['name'] else ''))
            if fn is None:
                continue

            _file = ReportFile(fn, ignore=ignored_lines.get(fn))
            for ln, cov in obj['lines'].iteritems():
                _file[int(ln)] = ReportLine(
                    coverage=cov,
                    sessions=[[sessionid, cov]]
                )

            report.append(_file)

    return report
