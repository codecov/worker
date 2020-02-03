from covreports.reports.resources import Report, ReportFile
from covreports.reports.types import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class RspecProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return content.get('command_name') == 'RSpec'

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        return from_json(content, path_fixer, ignored_lines, sessionid)


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
