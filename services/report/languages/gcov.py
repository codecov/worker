import re

from covreports.helpers.yaml import walk
from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class GcovProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return detect(content)

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        settings = walk(repo_yaml, ('parsers', 'gcov'))
        return from_txt(name, content, path_fixer, ignored_lines, sessionid, settings)


ignored_lines = re.compile(r'(\{|\})(\s*\/\/.*)?').match
detect_loop = re.compile(r'^\s+(for|while)\s?\(').match
detect_conditional = re.compile(r'^\s+((if\s?\()|(\} else if\s?\())').match


def detect(report):
    return '0:Source:' in report.split('\n', 1)[0]


def from_txt(name, string, fix, ignored_lines, sesisonid, settings):
    # clean and strip lines
    filename, string = string.split('\n', 1)
    filename = filename.split(':')[3].lstrip('./')
    if name and name.endswith(filename+'.gcov'):
        filename = fix(name[:-5]) or fix(filename)
    else:
        filename = fix(filename)
    if not filename:
        return None

    report = Report()
    report.append(
        _process_gcov_file(filename, ignored_lines.get(filename), string, sesisonid, settings)
    )
    return report


def _process_gcov_file(filename, ignore_func, gcov, sesisonid, settings):
    ignore = False
    ln = None
    next_is_func = False
    data = None

    _cur_branch_detected = None
    _cur_line_branch = None
    line_branches = {}
    lines = {}

    for line in gcov.splitlines():
        if 'LCOV_EXCL_START' in line:
            ignore = True

        elif 'LCOV_EXCL_END' in line or 'LCOV_EXCL_STOP' in line:
            ignore = False

        elif ignore:
            pass

        elif 'LCOV_EXCL_LINE' in line:
            pass

        elif line[:4] == 'func':
            # for next line
            next_is_func = True

        elif line[:4] == 'bran' and ln in lines:
            if _cur_branch_detected is False:
                # skip walking/regexp checks because of repeated branchs
                continue

            elif _cur_branch_detected is None:
                _cur_branch_detected = False  # first set to false, prove me true

                # class
                if lines[ln][1] == 'm':
                    if walk(settings, ('branch_detection', 'method')) is not True:
                        continue
                # loop
                elif detect_loop(data):
                    lines[ln] = (lines[ln][0], 'b')
                    if walk(settings, ('branch_detection', 'loop')) is not True:
                        continue
                # conditional
                elif detect_conditional(data):
                    lines[ln] = (lines[ln][0], 'b')
                    if walk(settings, ('branch_detection', 'conditional')) is not True:
                        continue
                # else macro
                elif walk(settings, ('branch_detection', 'macro')) is not True:
                    continue

                _cur_branch_detected = True  # proven true
                _cur_line_branch = line_branches.setdefault(ln, [0, 0])

            # add a hit
            if 'taken 0' not in line and 'never executed' not in line:
                _cur_line_branch[0] += 1

            # add to total
            _cur_line_branch[1] += 1

        elif line[:4] == 'call':
            continue

        else:
            _cur_branch_detected = None
            _cur_line_branch = None

            line = line.split(':', 2)
            if len(line) != 3:
                ln = None
                continue

            elif line[2].strip() == '}':
                # skip ending bracket lines
                continue

            elif line[2].startswith('@implementation'):
                # skip @implementation string;
                continue

            if filename.endswith('.swift'):
                # swift if reversed
                ln, hit, data = tuple(line)
            else:
                hit, ln, data = tuple(line)

            if ignored_lines(data):
                # skip bracket lines
                ln = None
                continue

            elif '-' in hit:
                ln = None
                continue

            hit = hit.strip()
            try:
                ln = int(ln.strip())
            except Exception:
                continue

            if hit == '#####':
                if data.strip().startswith(('inline', 'static')):
                    ln = None
                    continue

                coverage = 0

            elif hit == '=====':
                coverage = 0

            else:
                try:
                    coverage = int(hit)
                except Exception:
                    # https://app.getsentry.com/codecov/v4/issues/125373723/
                    ln = None
                    continue

            if next_is_func:
                lines[ln] = (coverage, 'm')
            else:
                lines[ln] = (coverage, None)

            next_is_func = False

    _file = ReportFile(filename, ignore=ignore_func)
    for ln, (coverage, _type) in lines.items():
        branches = line_branches.get(ln)
        if branches:
            coverage = '%s/%s' % tuple(branches)

        _file.append(ln, ReportLine(coverage, _type, [[sesisonid, coverage]]))

    return _file
