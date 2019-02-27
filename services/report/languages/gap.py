from json import loads

from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def detect(string):
    _string = string.split('\n', 1)[0]
    return '"Type":' in _string and '"File":' in _string


def from_string(string, fix, ignored_lines, sessionid):
    # https://github.com/codecov/support/issues/253
    report = Report()
    _file = None
    skip = True
    for line in string.splitlines():
        if line:
            line = loads(line)
            if line['Type'] == 'S':
                if _file is not None:
                    report.append(_file)
                filename = fix(line['File'])
                if filename:
                    _file = ReportFile(filename, ignore=ignored_lines.get(filename))
                    skip = False
                else:
                    skip = True

            elif skip:
                continue

            else:
                coverage = 0 if line['Type'] == 'R' else 1
                _file[line['Line']] = ReportLine(coverage, None, [[sessionid, coverage]])

    # append last file
    report.append(_file)
    return report
