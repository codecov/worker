import re

from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


docs = re.compile(r'^=+\n', re.M).split


def detect(report):
    return report[:7] == '======='


def from_txt(string, fix, ignored_lines, sessionid):
    filename = None
    report = Report()
    for string in docs(string.replace('\t', ' ')):
        string = string.strip()
        if string == 'Summary':
            filename = None
            continue

        elif string.endswith(('.lua', '.lisp')):
            filename = fix(string)
            if filename is None:
                continue

        elif filename:
            _file = ReportFile(filename, ignore=ignored_lines.get(filename))
            for ln, source in enumerate(string.splitlines(), start=1):
                try:
                    cov = source.strip().split(' ')[0]
                    cov = 0 if cov[-2:] in ('*0', '0') else int(cov)
                    _file[ln] = ReportLine(cov, None, [[sessionid, cov]])

                except:
                    pass

            report.append(_file)

    return report
