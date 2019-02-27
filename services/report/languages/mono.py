from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_xml(xml, fix, ignored_lines, sessionid, yaml):
    report = Report()

    # loop through methods
    for method in xml.getiterator('method'):
        # get file name
        filename = fix(method.attrib['filename'])
        if filename is None:
            continue

        # get file
        _file = report.get(filename)
        if not _file:
            _file = ReportFile(filename,
                               ignore=ignored_lines.get(filename))

        # loop through statements
        for line in method.getiterator('statement'):
            line = line.attrib
            coverage = int(line['counter'])

            _file.append(int(line['line']),
                         ReportLine(coverage=coverage,
                                    sessions=[[sessionid, coverage]]))

        report.append(_file)

    return report
