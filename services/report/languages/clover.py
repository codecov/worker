from timestring import Date

from services.yaml import read_yaml_field
from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor


class CloverProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return bool(content.tag == 'coverage' and content.attrib.get('generated'))

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        return from_xml(content, path_fixer, ignored_lines, sessionid, repo_yaml)


def get_end_of_file(filename, xmlfile):
    """
    php reports have shown to include
    exrta coverage data that extend
    past the source code line count
    """
    if filename.endswith('.php'):
        for metrics in xmlfile.iter('metrics'):
            try:
                return int(metrics.attrib['loc'])
            except Exception:
                pass


def from_xml(xml, fix, ignored_lines, sessionid, yaml):
    if read_yaml_field(yaml, ('codecov', 'max_report_age'), '12h ago'):
        try:
            timestamp = next(xml.iter('coverage')).get('generated')
            if '-' in timestamp:
                t = timestamp.split('-')
                timestamp = t[1] + '-' + t[0] + '-' + t[2]
            if timestamp and Date(timestamp) < read_yaml_field(yaml, ('codecov', 'max_report_age'), '12h ago'):
                # report expired over 12 hours ago
                raise ReportExpiredException('Clover report expired %s' % timestamp)
        except StopIteration:
            pass

    files = {}
    for f in xml.iter('file'):
        filename = f.attrib.get('path') or f.attrib['name']

        # skip empty file documents
        if (
            '{' in filename or
            ('/vendor/' in ('/'+filename) and filename.endswith('.php')) or
            f.find('line') is None
        ):
            continue

        if filename not in files:
            files[filename] = ReportFile(filename)

        _file = files[filename]

        # fix extra lines
        eof = get_end_of_file(filename, f)

        # process coverage
        for line in f.iter('line'):
            attribs = line.attrib
            ln = int(attribs['num'])
            complexity = None

            # skip line
            if ln < 1 or (eof and ln > eof):
                continue

            # [typescript] https://github.com/gotwarlost/istanbul/blob/89e338fcb1c8a7dea3b9e8f851aa55de2bc3abee/lib/report/clover.js#L108-L110
            if attribs['type'] == 'cond':
                _type = 'b'
                t, f = int(attribs['truecount']), int(attribs['falsecount'])
                if t == f == 0:
                    coverage = '0/2'
                elif t == 0 or f == 0:
                    coverage = '1/2'
                else:
                    coverage = '2/2'

            elif attribs['type'] == 'method':
                coverage = int(attribs.get('count') or 0)
                _type = 'm'
                complexity = int(attribs.get('complexity') or 0)
                # <line num="44" type="method" name="doRun" visibility="public" complexity="5" crap="5.20" count="1"/>

            else:
                coverage = int(attribs.get('count') or 0)
                _type = None

            # add line to report
            _file[ln] = ReportLine(coverage=coverage,
                                   type=_type,
                                   sessions=[[sessionid, coverage, None, None, complexity]],
                                   complexity=complexity)

    report = Report()
    for f in files.values():
        report.append((f))
    report.resolve_paths([(f, fix(f)) for f in files.keys()])
    report.ignore_lines(ignored_lines)

    return report
