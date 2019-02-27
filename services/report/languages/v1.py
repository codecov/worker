from app.helpers.reports import list_to_dict

from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine


def from_json(json, fix, ignored_lines, sessionid, config):
    if type(json['coverage']) is dict:
        # messages = json.get('messages', {})
        report = Report()
        for fn, lns in json['coverage'].iteritems():
            fn = fix(fn)
            if fn is None:
                continue

            lns = list_to_dict(lns)
            if lns:
                _file = ReportFile(fn, ignore=ignored_lines.get(fn))
                for ln, cov in lns.iteritems():
                    if int(ln) > 0:
                        if isinstance(cov, basestring):
                            try:
                                int(cov)
                            except:
                                pass
                            else:
                                cov = int(cov)

                        # message = messages.get(fn, {}).get(ln)
                        _file[int(ln)] = ReportLine(coverage=cov,
                                                    type='b' if type(cov) in (str, unicode, bool) else None,
                                                    sessions=[[sessionid, cov]],
                                                    messages=None)

                report.append(_file)

        return report
