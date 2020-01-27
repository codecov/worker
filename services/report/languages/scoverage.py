from covreports.reports.resources import Report, ReportFile
from covreports.reports.types import ReportLine
from covreports.helpers.numeric import maxint
from services.report.languages.base import BaseLanguageProcessor


class SCoverageProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return bool(content.tag == 'statements')

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        return from_xml(content, path_fixer, ignored_lines, sessionid)


def from_xml(xml, fix, ignored_lines, sessionid):
    report = Report()
    ignore = []
    cache_fixes = {}
    _cur_file_name = None
    files = {}
    for statement in xml.iter('statement'):
        # Determine the path
        unfixed_path = next(statement.iter('source')).text
        if unfixed_path in ignore:
            continue

        elif unfixed_path in cache_fixes:
            # cached results
            filename = cache_fixes[unfixed_path]

        else:
            # fix path
            filename = fix(unfixed_path)
            if filename is None:
                # add unfixed to list of ignored
                ignore.append(unfixed_path)
                continue

            # cache result (unfixed => filenmae)
            cache_fixes[unfixed_path] = filename

        # Get the file
        if filename != _cur_file_name:
            _cur_file_name = filename
            _file = files.get(filename)
            if not _file:
                _file = ReportFile(filename, ignore=ignored_lines.get(filename))
                files[filename] = _file

        # Add the line
        ln = int(next(statement.iter('line')).text)
        hits = next(statement.iter('count')).text
        try:
            if next(statement.iter('ignored')).text == 'true':
                continue
        except StopIteration:
            pass

        if next(statement.iter('branch')).text == 'true':
            cov = '%s/2' % hits
            _file[ln] = ReportLine(cov, 'b', [[sessionid, cov]])
        else:
            cov = maxint(hits)
            _file[ln] = ReportLine(cov, None, [[sessionid, cov]])

    for v in files.values():
        report.append(v)

    return report
