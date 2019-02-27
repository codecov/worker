from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_xml(xml, fix, ignored_lines, sessionid):
    report = Report()
    for module in xml.getiterator('module'):
        file_by_source = {}
        # loop through sources
        for sf in module.getiterator('source_file'):
            filename = fix(sf.attrib['path'].replace('\\', '/'))
            if filename:
                file_by_source[sf.attrib['id']] = ReportFile(filename,
                                                             ignore=ignored_lines.get(filename))

        if file_by_source:
            # loop through each line
            for line in module.getiterator('range'):
                line = line.attrib
                _file = file_by_source.get(line['source_id'])
                if _file is not None:
                    coverage = line['covered']
                    coverage = 1 if coverage == 'yes' else 0 if coverage == 'no' else True
                    for ln in xrange(int(line['start_line']), int(line['end_line'])+1):
                        _file[ln] = ReportLine(coverage, None, [[sessionid, coverage]])

            # add files
            map(report.append, file_by_source.values())

    return report
