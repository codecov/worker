from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_xml(xml, fix, ignored_lines, sessionid):
    file_by_source = {}
    for source in xml.getiterator('SourceFileNames'):
        filename = fix(source.find('SourceFileName').text.replace('\\', '/'))
        if filename:
            file_by_source[source.find('SourceFileID').text] = ReportFile(filename,
                                                                          ignore=ignored_lines.get(filename))

    for line in xml.getiterator('Lines'):
        _file = file_by_source.get(line.find('SourceFileID').text)
        if _file is not None:
            # 0 == hit, 1 == partial, 2 == miss
            cov = line.find('Coverage').text
            cov = 1 if cov == '0' else 0 if cov == '2' else True
            for ln in xrange(int(line.find('LnStart').text), int(line.find('LnEnd').text)+1):
                _file[ln] = ReportLine(cov, None, [[sessionid, cov]])

    report = Report()
    map(report.append, file_by_source.values())
    return report
