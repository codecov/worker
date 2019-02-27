from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_json(data_dict, fix, ignored_lines, sessionid):
    """
    Report example

      uploader: R
      files: []
        name:
        coverage: [null]
    """
    report = Report()

    for data in data_dict['files']:
        filename = fix(data['name'])
        if filename:
            _file = ReportFile(filename, ignore=ignored_lines.get(filename))
            fs = _file.__setitem__
            [fs(ln, ReportLine(int(cov), None, [[sessionid, int(cov)]]))
             for ln, cov in enumerate(data['coverage'])
             if cov is not None]
            report.append(_file)

    return report
