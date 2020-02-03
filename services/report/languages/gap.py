from json import loads, dumps

from covreports.reports.resources import Report, ReportFile
from covreports.reports.types import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class GapProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        if not isinstance(content, str):
            # Its a list of jsons, so the system might mistake this as a json type
            content = dumps(content)
        return detect(content)

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        if not isinstance(content, str):
            content = dumps(content)
        return from_string(content, path_fixer, ignored_lines, sessionid)


def detect(string):
    _string = string.split('\n', 1)[0]
    try:
        val = loads(_string)
        return 'Type' in val and 'File' in val
    except ValueError as ex:
        return False


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
