from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine
from covreports.helpers.numeric import maxint


def from_xml(xml, fix, ignored_lines, sessionid):
    report = Report()
    ignore = []
    cache_fixes = {}
    _cur_file_name = None
    files = {}
    for statement in xml.getiterator('statement'):
        # Determine the path
        unfixed_path = statement.getiterator('source').next().text
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
        ln = int(statement.getiterator('line').next().text)
        hits = statement.getiterator('count').next().text
        try:
            if statement.getiterator('ignored').next().text == 'true':
                continue
        except:
            pass

        if statement.getiterator('branch').next().text == 'true':
            cov = '%s/2' % hits
            _file[ln] = ReportLine(cov, 'b', [[sessionid, cov]])
        else:
            cov = maxint(hits)
            _file[ln] = ReportLine(cov, None, [[sessionid, cov]])

    map(report.append, files.values())

    return report
