from collections import defaultdict

from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class LcovProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return detect(content)

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        return from_txt(content, path_fixer, ignored_lines, sessionid)


def detect(report):
    return '\nend_of_record' in report


def from_txt(reports, fix, ignored_lines, sessionid):
    # http://ltp.sourceforge.net/coverage/lcov/geninfo.1.php
    report = Report()
    # merge same files
    for string in reports.split('\nend_of_record'):
        report.append(_process_file(string, fix, ignored_lines, sessionid))

    return report


def _process_file(doc, fix, ignored_lines, sessionid):
    lines = {}
    branches = defaultdict(dict)
    fln, fh = {}, {}
    JS = False
    CPP = False
    skip_lines = []
    _file = None
    for line in doc.splitlines():
        line = line.strip()
        if line == '' or ':' not in line:
            continue

        method, content = line.split(':', 1)
        content = content.strip()
        if method in ('TN', 'LF', 'LH', 'BRF', 'BRH'):
            # TN: test title
            # LF: lines found
            # LH: lines hit
            # FNF: functions found
            # FNH: functions hit
            # BRF: branches found
            # BRH: branches hit
            continue

        elif method == 'SF':
            """
            For  each  source  file  referenced in the .da file, there is a section
            containing filename and coverage data:

            SF:<absolute path to the source file>
            """
            # file name
            content = fix(content)
            if content is None:
                return None

            _file = ReportFile(content, ignore=ignored_lines.get(content))
            JS = (content[-3:] == '.js')
            CPP = (content[-4:] == '.cpp')

        elif method == 'DA':
            """
            Then there is a list of execution counts for each instrumented line
            (i.e. a line which resulted in executable code):

            DA:<line number>,<execution count>[,<checksum>]
            """
            #  DA:<line number>,<execution count>[,<checksum>]
            if line.startswith('undefined,'):
                continue

            line, hit = content.split(',', 1)
            if line[0] in ('0', 'n') or hit[0] in ('=', 's'):
                continue

            if hit == 'undefined' or line == 'undefined':
                continue

            cov = int(hit)
            _file.append(int(line), ReportLine(cov, None, [[sessionid, cov]]))

        elif method == 'FN' and not JS:
            """
            Following is a list of line numbers for each function name found in the
            source file:

            FN:<line number of function start>,<function name>
            """
            line, name = content.split(',', 1)
            if CPP and name[:2] in ('_Z', '_G'):
                skip_lines.append(line)
                continue

            fln[name] = line

        elif method == 'FNDA' and not JS:
            #  FNDA:<execution count>,<function name>
            hit, name = content.split(',', 1)
            if CPP and name[0] == '_':
                skip_lines.append(line)
                continue

            if hit != '':
                fh[name] = int(hit)

        elif method == 'BRDA' and not JS:
            """
            Branch coverage information is stored which one line per branch:

              BRDA:<line number>,<block number>,<branch number>,<taken>

            Block  number  and  branch  number are gcc internal IDs for the branch.
            Taken is either "-" if the basic block containing the branch was  never
            executed or a number indicating how often that branch was taken.
            """
            # BRDA:<line number>,<block number>,<branch number>,<taken>
            ln, block, branch, taken = content.split(',', 3)
            if ln == '1' and _file.name.endswith('.ts'):
                continue

            elif ln not in ('0', ''):
                branches[ln]['%s:%s' % (block, branch)] = 0 if taken in ('-', '0') else 1

    # remove skipped
    [(branches.pop(sl, None), lines.pop(sl, None)) for sl in skip_lines]

    methods = fln.values()

    # work branches
    for ln, br in branches.items():
        s, li = sum(br.values()), len(br.values())
        mb = [bid for bid, cov in br.items() if cov == 0]
        cov = '%s/%s' % (s, li)
        # override bc inline js: """if (True) { echo() }"""
        _file[int(ln)] = ReportLine(cov,
                                    'm' if ln in methods else 'b',
                                    [[sessionid, cov, mb if mb != [] else None]])

    return _file
