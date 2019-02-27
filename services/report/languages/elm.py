from covreports.resources import Report, ReportFile
from covreports.utils.tuples import ReportLine, LineSession


def from_json(json, fix, ignored_lines, sessionid):
    report = Report()
    for name, data in json['coverageData'].iteritems():
        fn = fix(json['moduleMap'][name])
        if fn is None:
            continue

        _file = ReportFile(fn, ignore=ignored_lines.get(fn))

        for sec in data:
            cov = sec.get('count', 0)
            complexity = sec.get('complexity')
            sl, sc = sec['from']['line'], sec['from']['column']
            el, ec = sec['to']['line'], sec['to']['column']
            _file[sl] = ReportLine(
                coverage=cov,
                sessions=[
                    LineSession(
                        id=sessionid,
                        coverage=cov,
                        partials=[[sc, ec if el == sl else None, cov]]
                    )
                ],
                complexity=complexity
            )
            if el > sl:
                for ln in range(sl, el):
                    _file[ln] = ReportLine(coverage=cov,
                                           sessions=[[sessionid, cov]],
                                           complexity=complexity)
                _file[sl] = ReportLine(
                    coverage=cov,
                    sessions=[
                        LineSession(
                            id=sessionid,
                            coverage=cov,
                            partials=[[None, ec, cov]]
                        )
                    ],
                    complexity=complexity
                )

        report.append(_file)

    return report
