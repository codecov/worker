from collections import defaultdict

from services.report.languages.helpers import combine_partials
from covreports.helpers.yaml import walk
from covreports.resources import Report, ReportFile
from covreports.utils.merge import partials_to_line
from covreports.utils.tuples import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class GoProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return content[:6] == 'mode: ' or '.go:' in first_line

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml):
        return from_txt(content, path_fixer, ignored_lines, sessionid, repo_yaml)


def from_txt(string, fix, ignored_lines, sessionid, yaml):
    """
    mode: count
    github.com/codecov/sample_go/sample_go.go:7.14,9.2 1 1
    github.com/codecov/sample_go/sample_go.go:11.26,13.2 1 1
    github.com/codecov/sample_go/sample_go.go:15.19,17.2 1 0

    Ending bracket is here                             v
    github.com/codecov/sample_go/sample_go.go:15.19,17.2 1 0

    All other continuation > .2 should continue
    github.com/codecov/sample_go/sample_go.go:15.19,17.9 1 0

    Need to be concious of customers whom have reports merged in the following way:
    FILE:1.0,2.0 1 0
    ...
    FILE:1.0,2.0 1 1
    ...
    FILE:1.0,2.0 1 0
    Need to respect the coverage
    """
    _cur_file = None
    lines = None
    ignored_files = []
    file_name_replacement = {}  # {old_name: new_name}
    files = {}  # {new_name: <lines defaultdict(list)>}
    disable_default_path_fixes = walk(yaml, ('codecov', 'disable_default_path_fixes'), False)

    for line in string.splitlines():
        if not line:
            continue

        elif line[:6] == 'mode: ':
            continue

        # prepare data
        filename, data = line.split(':', 1)
        if data.endswith('%'):
            # File outline e.g., "github.com/nfisher/rsqf/rsqf.go:19: calcP 100.0%"
            continue

        # if we are on the same file name we can pass this
        if filename in ignored_files:
            continue

        if _cur_file != filename:
            _cur_file = filename
            if filename in file_name_replacement:
                filename = file_name_replacement[filename]
            else:
                fixed = fix(filename)

                filename = file_name_replacement[filename] = fixed
                if filename is None:
                    ignored_files.append(_cur_file)
                    _cur_file = None
                    continue

            lines = files.setdefault(filename, defaultdict(list))

        columns, _, hits = data.split(' ', 2)
        hits = int(hits)
        sl, el = columns.split(',', 1)
        sl, sc = list(map(int, sl.split('.', 1)))
        el, ec = list(map(int, el.split('.', 1)))

        # add start of line
        if sl == el:
            lines[sl].append([sc, ec, hits])
        else:
            lines[sl].append([sc, None, hits])
            # add middles
            [lines[ln].append([0, None, hits]) for ln in range(sl + 1, el)]
            if ec > 2:
                # add end of line
                lines[el].append([None, ec, hits])

    # create a file
    report = Report()
    for filename, lines in files.items():
        _file = ReportFile(filename, ignore=ignored_lines.get(filename))
        for ln, partials in lines.items():
            best_in_partials = max(map(lambda p: p[2], partials))
            partials = combine_partials(partials)
            if partials:
                cov = partials_to_line(partials)
                if partials[0] == [0, None, cov] or partials[0] == [None, None, cov]:
                    _file[ln] = ReportLine(cov, None, [[sessionid, cov]])
                else:
                    # partials
                    _file[ln] = ReportLine(cov, None, [[sessionid, cov]])
            else:
                _file[ln] = ReportLine(best_in_partials, None, [[sessionid, best_in_partials]])

        report.append(_file)

    return report
