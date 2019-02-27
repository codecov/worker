from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine, LineSession


def from_xml(xml, fix, ignored_lines, sessionid):
    # dict of {"fileid": "path"}
    file_by_id = {}
    file_by_id_get = file_by_id.get
    for f in xml.getiterator('File'):
        filename = fix(f.attrib['Name'].replace('\\', '/'))
        if filename:
            file_by_id[str(f.attrib['Index'])] = ReportFile(filename,
                                                            ignore=ignored_lines.get(filename))

    for statement in xml.getiterator('Statement'):
        _file = file_by_id.get(str(statement.attrib['FileIndex']))
        if _file is not None:
            sl = int(statement.attrib['Line'])
            el = int(statement.attrib['EndLine'])
            sc = int(statement.attrib['Column'])
            ec = int(statement.attrib['EndColumn'])
            cov = 1 if statement.attrib['Covered'] == 'True' else 0
            if sl == el:
                _file.append(sl,
                             ReportLine(coverage=cov,
                                        sessions=[
                                            LineSession(id=sessionid,
                                                        coverage=cov,
                                                        partials=[[sc, ec, cov]])]))
            else:
                _file.append(sl,
                             ReportLine(coverage=cov,
                                        sessions=[[sessionid, cov]]))

    report = Report()
    report_append = report.append
    for fid, content in file_by_id.iteritems():
        report_append(content)

    return report
