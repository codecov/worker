from covreports.reports.resources import Report, ReportFile
from covreports.reports.types import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class DLSTProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return bool(content[-7:] == 'covered')

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        return from_string(name, content, path_fixer, ignored_lines, sessionid)


def from_string(filename, string, fix, ignored_lines, sessionid):
    string = string.splitlines()
    if filename:
        # src/file.lst => src/file.d
        filename = fix('%sd' % filename[:-3])

    if not filename:
        # file.d => src/file.d
        filename = string.pop(-1).split(' is ', 1)[0]
        if filename.startswith('source '):
            filename = filename[7:]

        filename = fix(filename)
        if not filename:
            return None

    _file = ReportFile(filename, ignore=ignored_lines.get(filename))
    for ln, line in enumerate(string, start=1):
        try:
            coverage = int(line.split('|', 1)[0].strip())
            _file[ln] = ReportLine(coverage, None, [[sessionid, coverage]])
        except Exception:
            # not a vaild line
            pass

    report = Report()
    report.append(_file)
    return report
